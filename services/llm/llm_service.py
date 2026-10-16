import json
import re
import time
from itertools import groupby
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.llm import BATCH_SIZE, MAX_ITEM_CHARS, PROMPT_VERSION, SUMMARY_MAX_CHARS
from core.constants.prompts import SYSTEM_PROMPT
from core.constants.taxonomy import TOPICS
from core.logger import get_logger, log_event
from crud import item_crud, llm_usage_crud
from db.session import SessionLocal
from models.entry_model import Entry
from models.item_model import Item
from models.source_model import Source
from services.llm import lm_client
from services.llm.lm_client import LlmBudgetExhausted, LlmRateLimited, LlmUnavailable

logger = get_logger("summarizer")
llm_logger = get_logger("llm")


class Summary(BaseModel):
    """모델이 항목 하나에 대해 돌려주는 값."""

    n: int
    category: Literal["feature", "bugfix", "breaking", "security", "other"]
    topic: Literal[(*TOPICS, "")]
    importance: int = Field(ge=1, le=5)
    summary_ko: str = Field(min_length=1)

    @field_validator("summary_ko")
    @classmethod
    def check_summary(cls, value: str) -> str:
        """NUL 문자(`\\x00`)를 지우고 끝의 마침표를 떼며, "~다"로 끝나지 않거나 너무 길면 검증 실패로 돌려보낸다.

        PostgreSQL 문자열 컬럼은 NUL을 저장하지 못한다. 원문에 `\\x00` 이스케이프가 나오는 릴리스는 모델이 진짜 NUL을 돌려줘서 커밋이 실패하고 같은 묶음이 계속 재시도된다.

        Args:
            value: 모델이 만든 한 줄 요약
        Returns:
            NUL과 마침표를 뗀 요약
        """
        value = value.replace("\x00", "").strip().rstrip(".").strip()
        if not value.endswith("다"):
            raise ValueError("'~다'로 끝나지 않음")
        if len(value) > SUMMARY_MAX_CHARS:
            raise ValueError(f"길이 초과({len(value)}자)")
        return value


SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": Summary.model_json_schema()}},
    "required": ["items"],
}


def clean_text(text: str) -> str:
    """모델에 보내기 전에 요약에 필요 없는 PR 번호(`#1234`)와 작성자(`@name`)를 뺀다.

    Args:
        text: 항목 원문
    Returns:
        정리한 원문
    """
    text = re.sub(r"\(\s*(?:#\d+[,\s]*)+\)", "", text)
    text = re.sub(r"(?<![\w`])#\d+\b|(?<![\w`.])@[\w-]+\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def unseen_words(summary: str, original: str) -> list[str]:
    """요약에 나온 영어 단어 중 원문에 없는 것을 돌려준다. 모델이 지어낸 용어를 걸러내는 데 쓴다.

    원문 단어 2~5개의 머리글자를 이은 약어(`byte-order mark` → `BOM`)는 지어낸 말이 아니므로 통과시킨다.

    Args:
        summary: 한국어 요약
        original: 항목 원문
    Returns:
        원문에 없는 영어 단어 (대소문자 무시). 모두 있으면 빈 목록
    """
    lowered = original.lower()
    words = re.findall(r"[a-z0-9]+", lowered)
    acronyms = {"".join(w[0] for w in words[i : i + n]) for n in range(2, 6) for i in range(len(words) - n + 1)}
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", summary) if w.lower() not in lowered and w.lower() not in acronyms]


def _messages(source: Source, entry: Entry, texts: dict[int, str]) -> list[dict]:
    """모델에 보낼 메시지를 만든다.

    Args:
        source: 소스
        entry: 글(릴리스)
        texts: 번호별 항목 원문
    Returns:
        시스템과 사용자 메시지 목록
    """
    lines = "\n".join(f"{n}. {clean_text(text)[:MAX_ITEM_CHARS]}" for n, text in texts.items())
    user = f"도구: {source.name}\n버전: {entry.version or entry.title}\n\n{lines}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _parse(content: str, texts: dict[int, str]) -> tuple[dict[int, Summary], dict[int, str]]:
    """모델 답을 읽어 검증을 통과한 항목을 번호별로 돌려주고, 통과하지 못한 항목은 이유를 함께 돌려준다.

    Args:
        content: 모델 답 본문
        texts: 기다리는 번호별 항목 원문. 요약에 원문에 없는 영어 단어가 있으면 통과시키지 않는다
    Returns:
        (번호별 검증된 값, 통과하지 못한 번호별 이유). 주제가 목록에 없으면 빈 값으로 바꾼다
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        raw_items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return {}, {n: "응답 형식 오류(JSON)" for n in texts}

    result: dict[int, Summary] = {}
    reasons: dict[int, str] = {}
    for raw in raw_items if isinstance(raw_items, list) else []:
        n = raw.get("n") if isinstance(raw, dict) else None
        try:
            summary = Summary.model_validate(raw)
        except ValidationError as exc:
            error = exc.errors()[0]
            field = str(error["loc"][-1]) if error["loc"] else "형식"
            msg = error["msg"].removeprefix("Value error, ")
            if isinstance(n, int) and n in texts:
                reasons[n] = msg if field == "summary_ko" else f"{field}: {msg}"
            continue
        if summary.n not in texts or summary.n in result:
            continue
        bad = unseen_words(summary.summary_ko, texts[summary.n])
        if bad:
            reasons[summary.n] = "원문에 없는 영어: " + ", ".join(dict.fromkeys(bad))
            continue
        if summary.topic not in TOPICS:
            summary.topic = ""
        result[summary.n] = summary
    return result, {n: reasons.get(n, "모델이 이 번호를 빼먹음") for n in texts if n not in result}


_gemini_blocked_until = 0.0


def _model_name(provider: str) -> str:
    return settings.GEMINI_MODEL if provider == "gemini" else settings.LM_STUDIO_MODEL


def block_gemini() -> None:
    """한도 초과(429)나 인증 오류를 받은 Gemini를 `GEMINI_COOLDOWN_MIN`분 동안 쉬게 한다."""
    global _gemini_blocked_until
    _gemini_blocked_until = time.monotonic() + settings.GEMINI_COOLDOWN_MIN * 60


def pick_provider(db: Session) -> str | None:
    """이번에 쓸 제공자를 고른다.

    `LLM_PROVIDER`가 `local`이면 항상 로컬이다. `gemini`는 Gemini만 쓰고 한도가 차거나 쉬는 중이면 `None`이다.
    `auto`는 Gemini를 먼저 쓰고, 오늘 한도를 다 썼거나 쉬는 중이면 로컬로 넘어간다.

    Args:
        db: DB 세션
    Returns:
        `local`, `gemini`, 쓸 수 있는 제공자가 없으면 `None`
    """
    mode = settings.LLM_PROVIDER
    if mode == "local":
        return "local"
    ready = (
        bool(settings.GEMINI_API_KEY)
        and time.monotonic() >= _gemini_blocked_until
        and llm_usage_crud.calls_today(db, "gemini") < settings.GEMINI_DAILY_LIMIT
    )
    if ready:
        return "gemini"
    return "local" if mode == "auto" else None


def summarize_batch(db: Session, source: Source, entry: Entry, items: list[Item], provider: str = "local") -> None:
    """같은 릴리스의 항목 몇 개를 한 번에 요약해 결과를 항목에 채운다. 커밋은 부르는 쪽이 한다 (Gemini 호출 수를 세면서 한 번 커밋한다).

    검증에 실패한 항목만 `LLM_MAX_RETRIES`번까지 다시 보내고, 그래도 안 되면 `failed`로 두고 `attempts`를 올린다.
    Gemini는 호출마다 하루 한도를 확인하고 센다.

    Args:
        db: DB 세션
        source: 소스
        entry: 글(릴리스)
        items: 같은 글에 속한 항목들
        provider: `local` 또는 `gemini`
    Raises:
        lm_client.LlmRateLimited: 429를 받았을 때
        lm_client.LlmBudgetExhausted: Gemini의 오늘 호출 한도를 다 썼을 때
        lm_client.LlmUnavailable: 제공자에 닿지 못했을 때. 이때 항목 상태는 바꾸지 않는다
    """
    waiting = {n: item for n, item in enumerate(items, start=1)}
    attempts = 0
    reasons: dict[int, str] = {}
    model = _model_name(provider)
    for _ in range(settings.LLM_MAX_RETRIES + 1):
        if not waiting:
            break
        if provider == "gemini":
            if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
                raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
            llm_usage_crud.add_call(db, "gemini")
        attempts += 1
        completion = lm_client.complete(_messages(source, entry, {n: i.raw_text for n, i in waiting.items()}), SCHEMA, provider)
        model = completion.model
        parsed, reasons = _parse(completion.content, {n: i.raw_text for n, i in waiting.items()})
        for n, summary in parsed.items():
            item = waiting.pop(n)
            item.category = summary.category
            item.topic = summary.topic or None
            item.importance = summary.importance
            item.summary_ko = summary.summary_ko
            item.status = "done"
            item.model = model
            item.prompt_version = PROMPT_VERSION
            item.error = None

    log_event(
        llm_logger,
        event="batch",
        provider=provider,
        model=model,
        source=source.slug,
        version=entry.version or entry.title,
        items=len(items),
        done=len(items) - len(waiting),
        failed=len(waiting),
        attempts=attempts,
        prompt_version=PROMPT_VERSION,
    )
    for n, item in waiting.items():
        item.status = "failed"
        item.model = model
        item.prompt_version = PROMPT_VERSION
        item.error = f"{reasons.get(n, '검증 실패')} (시도 {attempts}회)"
        item.attempts = (item.attempts or 0) + 1


def summarize_pending(db: Session, limit: int, provider: str = "local") -> list[tuple[Item, Entry, Source]]:
    """요약을 기다리는 항목을 `limit`개까지 요약한다. 묶음마다 커밋해서 중간에 멈춰도 결과가 남는다.

    한 번에 보내는 개수는 제공자마다 다르다 (로컬 `BATCH_SIZE`, Gemini `GEMINI_BATCH_SIZE`).

    Args:
        db: DB 세션
        limit: 처리할 최대 항목 수
        provider: `local` 또는 `gemini`
    Returns:
        처리한 `(항목, 글, 소스)` 목록. 항목의 `status`가 `done` 또는 `failed`다
    Raises:
        lm_client.LlmUnavailable: 제공자에 닿지 못했을 때 (`LlmRateLimited`, `LlmBudgetExhausted` 포함). 그때까지 끝낸 묶음은 저장돼 있다
    """
    size = settings.GEMINI_BATCH_SIZE if provider == "gemini" else BATCH_SIZE
    rows = item_crud.list_pending_items(db, limit)
    processed: list[tuple[Item, Entry, Source]] = []
    for _, group in groupby(rows, key=lambda row: row[1].id):
        group_rows = list(group)
        entry, source = group_rows[0][1], group_rows[0][2]
        for start in range(0, len(group_rows), size):
            batch = group_rows[start : start + size]
            try:
                summarize_batch(db, source, entry, [row[0] for row in batch], provider)
                db.commit()
            except LlmUnavailable:
                raise
            except Exception as exc:
                db.rollback()
                logger.exception("summarize: %s %s 묶음 처리 실패", source.slug, entry.version or entry.id)
                item_crud.mark_failed(db, [row[0].id for row in batch], f"처리 오류({exc.__class__.__name__})")
                db.commit()
            processed.extend(batch)
            logger.info(
                "summarize[%s] %s %s: %d건 처리 (완료 %d, 실패 %d)",
                provider,
                source.slug,
                entry.version or entry.id,
                len(batch),
                sum(1 for row in batch if row[0].status == "done"),
                sum(1 for row in batch if row[0].status == "failed"),
            )
    return processed


def summarize_job() -> None:
    """스케줄러가 주기적으로 부른다. 요약 대기 항목이 없어질 때까지 `SUMMARIZE_BATCH_LIMIT`개씩 이어서 요약한다.

    제공자는 `pick_provider`가 고른다. Gemini가 한도 초과(429)나 호출 한도 소진, 인증 오류를 내면 롤백한 뒤 Gemini를 쉬게 하고
    (`auto`면) 로컬로 이어서 한다. 로컬에 닿지 못하면 경고만 남기고 끝낸다 (다음 주기에 다시 시도). 한 번에 하나만 돈다.
    """
    total = done = failed = 0
    with SessionLocal() as db:
        while True:
            provider = pick_provider(db)
            if provider is None:
                logger.info("summarize: 쓸 수 있는 제공자가 없어 쉰다 (Gemini 한도 소진 또는 대기 중)")
                break
            try:
                rows = summarize_pending(db, settings.SUMMARIZE_BATCH_LIMIT, provider)
            except (LlmRateLimited, LlmBudgetExhausted) as exc:
                db.rollback()
                logger.warning("summarize[%s]: 쉼 (%s)", provider, exc)
                block_gemini()
                continue
            except LlmUnavailable as exc:
                db.rollback()
                logger.warning("summarize[%s]: 중단 (%s)", provider, exc)
                if provider == "gemini" and settings.LLM_PROVIDER == "auto":
                    block_gemini()
                    continue
                break
            except Exception:
                db.rollback()
                logger.exception("summarize: 실패")
                break
            finished = [row for row in rows if row[0].status in ("done", "failed")]
            total += len(finished)
            done += sum(1 for row in finished if row[0].status == "done")
            failed += sum(1 for row in finished if row[0].status == "failed")
            if not finished:
                break
    if total:
        logger.info("summarize: %d건 처리 (완료 %d, 실패 %d)", total, done, failed)


def requeue_failed_job() -> None:
    """하루에 한 번 실패한 항목(시도 `FAILED_MAX_ATTEMPTS`회 미만)을 요약 대기로 되돌린다."""
    with SessionLocal() as db:
        count = item_crud.requeue_failed(db, settings.FAILED_MAX_ATTEMPTS)
    if count:
        logger.info("requeue: 실패 항목 %d건을 다시 대기로 돌렸다", count)