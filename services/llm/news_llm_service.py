import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.news import (
    NEWS_BATCH_SIZE,
    NEWS_PROMPT_CHARS,
    NEWS_PROMPT_VERSION,
    NEWS_SUMMARY_MAX,
    NEWS_TITLE_MAX,
    NEWS_TYPES,
)
from core.constants.prompts import NEWS_PROMPT
from core.constants.taxonomy import TOPICS
from core.logger import get_logger, log_event
from crud import llm_usage_crud, news_crud
from db.session import SessionLocal
from models.news_model import News
from services.llm import lm_client
from services.llm.lm_client import LlmBudgetExhausted, LlmRateLimited, LlmUnavailable
from services.llm.llm_service import LLM_LOCK, block_gemini, gemini_ready, unseen_words

logger = get_logger("news_summarizer")
llm_logger = get_logger("llm")


class NewsSummary(BaseModel):
    """모델이 공식 발표 글 하나에 대해 돌려주는 값."""

    n: int
    relevant: bool
    reason: str
    news_type: Literal[tuple(NEWS_TYPES)]
    topic: Literal[(*TOPICS, "")]
    importance: int = Field(ge=1, le=5)
    title_ko: str
    summary_ko: str

    @model_validator(mode="after")
    def check(self) -> "NewsSummary":
        """NUL 문자를 지우고, 관련 있는 글이면 제목과 요약이 있는지, 요약이 "~다"로 끝나는지, 길이가 넘지 않는지 확인한다.

        Returns:
            다듬은 값
        Raises:
            ValueError: 관련 있는 글의 제목이나 요약이 비었거나 규칙에 맞지 않을 때
        """
        self.reason = self.reason.replace("\x00", "").strip()
        self.title_ko = self.title_ko.replace("\x00", "").strip()
        self.summary_ko = self.summary_ko.replace("\x00", "").strip()
        if not self.relevant:
            return self
        if not self.title_ko or len(self.title_ko) > NEWS_TITLE_MAX:
            raise ValueError(f"제목 오류({len(self.title_ko)}자)")
        summary = self.summary_ko.rstrip(".").strip()
        if not summary.endswith("다"):
            raise ValueError("요약이 '~다'로 끝나지 않음")
        if len(summary) > NEWS_SUMMARY_MAX:
            raise ValueError(f"요약 길이 초과({len(summary)}자)")
        self.summary_ko = summary
        return self


NEWS_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": NewsSummary.model_json_schema()}},
    "required": ["items"],
}


def _messages(articles: dict[int, News]) -> list[dict]:
    """모델에 보낼 메시지를 만든다.

    Args:
        articles: 번호별 글
    Returns:
        시스템과 사용자 메시지 목록
    """
    blocks = [
        f"{n}. [{a.company}] {a.title} ({a.published_at:%Y-%m-%d})\n{a.body_raw[:NEWS_PROMPT_CHARS]}" for n, a in articles.items()
    ]
    return [{"role": "system", "content": NEWS_PROMPT}, {"role": "user", "content": "\n\n".join(blocks)}]


def _parse(content: str, articles: dict[int, News]) -> tuple[dict[int, NewsSummary], dict[int, str]]:
    """모델 답을 읽어 검증을 통과한 글을 번호별로 돌려주고, 통과하지 못한 글은 이유를 함께 돌려준다.

    Args:
        content: 모델 답 본문
        articles: 기다리는 번호별 글. 관련 있는 글의 제목과 요약에 원문에 없는 영어 단어가 있으면 통과시키지 않는다
    Returns:
        (번호별 검증된 값, 통과하지 못한 번호별 이유). 주제가 목록에 없으면 빈 값으로 바꾼다
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        raw_items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return {}, {n: "응답 형식 오류(JSON)" for n in articles}

    result: dict[int, NewsSummary] = {}
    reasons: dict[int, str] = {}
    for raw in raw_items if isinstance(raw_items, list) else []:
        n = raw.get("n") if isinstance(raw, dict) else None
        try:
            summary = NewsSummary.model_validate(raw)
        except ValidationError as exc:
            if isinstance(n, int) and n in articles:
                error = exc.errors()[0]
                reasons[n] = error["msg"].removeprefix("Value error, ")
            continue
        if summary.n not in articles or summary.n in result:
            continue
        article = articles[summary.n]
        if summary.relevant:
            bad = unseen_words(f"{summary.title_ko} {summary.summary_ko}", f"{article.company} {article.title} {article.body_raw}")
            if bad:
                reasons[summary.n] = "원문에 없는 영어 · 외국 글자: " + ", ".join(dict.fromkeys(bad))
                continue
        result[summary.n] = summary
    return result, {n: reasons.get(n, "모델이 이 번호를 빼먹음") for n in articles if n not in result}


def summarize_batch(db: Session, batch: list[News]) -> None:
    """공식 발표 글 몇 개를 한 번에 요약하고 관련 여부를 가려 결과를 채운다. 커밋은 부르는 쪽이 한다.

    관련 있으면 `done`, 관련 없으면 `skipped`로 둔다. 검증에 실패한 글만 `LLM_MAX_RETRIES`번까지 다시 보내고, 그래도 안 되면 `failed`로 두고 `attempts`를 올린다.
    호출마다 하루 한도를 확인하고 센다.

    Args:
        db: DB 세션
        batch: 같은 호출에 보낼 글
    Raises:
        lm_client.LlmRateLimited: 429를 받았을 때
        lm_client.LlmBudgetExhausted: 오늘 호출 한도를 다 썼을 때
        lm_client.LlmUnavailable: Gemini에 닿지 못했을 때. 이때 글 상태는 바꾸지 않는다
    """
    waiting = {n: article for n, article in enumerate(batch, start=1)}
    attempts = 0
    reasons: dict[int, str] = {}
    model = settings.GEMINI_MODEL
    skipped = 0
    for _ in range(settings.LLM_MAX_RETRIES + 1):
        if not waiting:
            break
        if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
            raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
        llm_usage_crud.add_call(db, "gemini")
        attempts += 1
        completion = lm_client.complete(_messages(waiting), NEWS_SCHEMA)
        model = completion.model
        parsed, reasons = _parse(completion.content, waiting)
        for n, summary in parsed.items():
            article = waiting.pop(n)
            article.news_type = summary.news_type
            article.model = model
            article.prompt_version = NEWS_PROMPT_VERSION
            article.error = None
            if summary.relevant:
                article.status = "done"
                article.title_ko = summary.title_ko
                article.summary_ko = summary.summary_ko
                article.topic = summary.topic or None
                article.importance = summary.importance
                article.reason = None
            else:
                skipped += 1
                article.status = "skipped"
                article.title_ko = article.summary_ko = article.topic = article.importance = None
                article.reason = summary.reason or None

    log_event(
        llm_logger,
        event="news_batch",
        provider="gemini",
        model=model,
        items=len(batch),
        done=len(batch) - len(waiting) - skipped,
        skipped=skipped,
        failed=len(waiting),
        attempts=attempts,
        prompt_version=NEWS_PROMPT_VERSION,
    )
    for n, article in waiting.items():
        article.status = "failed"
        article.model = model
        article.prompt_version = NEWS_PROMPT_VERSION
        article.error = f"{reasons.get(n, '검증 실패')} (시도 {attempts}회)"
        article.attempts = (article.attempts or 0) + 1


def summarize_pending(db: Session, limit: int) -> list[News]:
    """요약을 기다리는 공식 발표 글을 `limit`개까지 요약한다. 묶음마다 커밋해서 중간에 멈춰도 결과가 남는다.

    Args:
        db: DB 세션
        limit: 처리할 최대 글 수
    Returns:
        처리한 글 목록. `status`가 `done`, `skipped`, `failed`다
    Raises:
        lm_client.LlmUnavailable: Gemini에 닿지 못했을 때 (`LlmRateLimited`, `LlmBudgetExhausted` 포함). 그때까지 끝낸 묶음은 저장돼 있다
    """
    rows = news_crud.list_pending(db, limit)
    processed: list[News] = []
    for start in range(0, len(rows), NEWS_BATCH_SIZE):
        batch = rows[start : start + NEWS_BATCH_SIZE]
        try:
            summarize_batch(db, batch)
            db.commit()
        except LlmUnavailable:
            raise
        except Exception as exc:
            db.rollback()
            logger.exception("news summarize: 묶음 처리 실패 (%d건)", len(batch))
            for article in batch:
                article.status = "failed"
                article.error = f"처리 오류({exc.__class__.__name__})"
                article.attempts = (article.attempts or 0) + 1
            db.commit()
        processed.extend(batch)
        logger.info(
            "news summarize: %d건 처리 (완료 %d, 제외 %d, 실패 %d)",
            len(batch),
            sum(1 for a in batch if a.status == "done"),
            sum(1 for a in batch if a.status == "skipped"),
            sum(1 for a in batch if a.status == "failed"),
        )
    return processed


def summarize_news_job() -> None:
    """스케줄러가 주기적으로 부르는 뉴스 요약 작업. 릴리스 요약 작업과 동시에 Gemini를 부르지 않게 `LLM_LOCK`을 잡는다.

    대기 글이 없어질 때까지 `SUMMARIZE_BATCH_LIMIT`개씩 이어서 요약한다. 429나 호출 한도 소진이면 Gemini를 쉬게 하고 끝내고, 닿지 못하면 경고만 남기고 끝낸다.
    """
    total = done = skipped = failed = 0
    with LLM_LOCK, SessionLocal() as db:
        while gemini_ready(db):
            try:
                rows = summarize_pending(db, settings.SUMMARIZE_BATCH_LIMIT)
            except (LlmRateLimited, LlmBudgetExhausted) as exc:
                db.rollback()
                logger.warning("news summarize: 쉼 (%s)", exc)
                block_gemini()
                break
            except LlmUnavailable as exc:
                db.rollback()
                logger.warning("news summarize: 중단 (%s)", exc)
                break
            except Exception:
                db.rollback()
                logger.exception("news summarize: 실패")
                break
            if not rows:
                break
            total += len(rows)
            done += sum(1 for a in rows if a.status == "done")
            skipped += sum(1 for a in rows if a.status == "skipped")
            failed += sum(1 for a in rows if a.status == "failed")
    if total:
        logger.info("news summarize: %d건 처리 (완료 %d, 제외 %d, 실패 %d)", total, done, skipped, failed)