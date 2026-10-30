import json
import re
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ValidationError, model_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.monthly import (
    MONTHLY_BACKFILL_MONTHS,
    MONTHLY_DEADLINE_DAYS,
    MONTHLY_DEADLINE_LIMIT,
    MONTHLY_HEADLINE_MAX,
    MONTHLY_ITEM_LIMIT,
    MONTHLY_NEWS_LIMIT,
    MONTHLY_PICKS_MAX,
    MONTHLY_PICKS_MIN,
    MONTHLY_PROMPT_VERSION,
    MONTHLY_REASON_MAX,
    MONTHLY_RETRY_HOURS,
    MONTHLY_TODO_MAX,
    MONTHLY_TODOS_MAX,
    MONTHLY_TREND_MAX,
)
from core.constants.page import KST
from core.constants.prompts import MONTHLY_PROMPT
from core.logger import get_logger, log_event
from core.months import month_bounds, prev_month
from crud import deadline_crud, llm_usage_crud, monthly_crud
from db.session import SessionLocal
from services.llm import lm_client
from services.llm.lm_client import LlmBudgetExhausted, LlmRateLimited, LlmUnavailable
from services.llm.llm_service import LLM_LOCK, block_gemini, gemini_ready, unseen_words
from services.web.release_service import release_label, release_path

logger = get_logger("monthly")
llm_logger = get_logger("llm")

_QUOTES = str.maketrans("", "", '"“”')
_EXPERIENCE = re.compile(r"써 보니|써봤|체감|사용해 보니")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_failed: dict[date, datetime] = {}


class MonthlyRejected(Exception):
    """모델 답이 검증을 통과하지 못했을 때. `code`는 로그에 남길 분류이고, `hint`는 다음 시도에서 모델에게 알려 줄 이유다(글 내용은 담지 않는다)."""

    def __init__(self, code: str, hint: str):
        super().__init__(hint)
        self.code, self.hint = code, hint


def _clean(texts: list[str]) -> list[str]:
    """글마다 NUL 문자와 큰따옴표를 지우고 앞뒤 공백을 뗀다."""
    return [t.replace("\x00", "").translate(_QUOTES).strip() for t in texts]


def _plain_number(number: str) -> str:
    """정수의 앞자리 0을 뗀다(`09` → `9`). 날짜 `2026-09`를 글에서 `9월`로 쓸 수 있게 하려는 것이다. 소수는 그대로 둔다."""
    return number if "." in number else number.lstrip("0") or "0"


def _ends_with_da(text: str) -> bool:
    """모든 문장이 "~다"로 끝나는지 돌려준다."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    return bool(sentences) and all(s.rstrip(".").endswith("다") for s in sentences)


class MonthlyText(BaseModel):
    """모델이 돌려주는 월간 리포트 초안. 제목 후보, 흐름 문단, 고른 변경과 이유, 할 일과 문장이다."""

    headlines: list[str]
    trends: list[str]
    pick_ids: list[str]
    pick_reasons: list[str]
    todo_ids: list[str]
    todo_texts: list[str]

    @model_validator(mode="after")
    def check(self) -> "MonthlyText":
        """공백 · NUL 문자 · 큰따옴표를 지우고 개수 · 길이 · 문장 끝 · 경험 표현을 확인한다. 오류 문구는 모델에게 다시 알려 줄 수 있게 어긴 규칙과 지금 개수를 담는다.

        Returns:
            다듬은 값
        Raises:
            ValueError: 개수나 길이가 맞지 않거나, 문장이 "~다"로 끝나지 않거나, 경험 표현(써 보니, 체감 등)이 있을 때
        """
        self.headlines = [h.rstrip(".") for h in _clean(self.headlines)]
        self.trends, self.pick_reasons, self.todo_texts = _clean(self.trends), _clean(self.pick_reasons), _clean(self.todo_texts)
        self.pick_ids, self.todo_ids = _clean(self.pick_ids), _clean(self.todo_ids)
        if len(self.headlines) != 3 or any(not h or len(h) > MONTHLY_HEADLINE_MAX for h in self.headlines):
            raise ValueError(f"headlines는 3개이고 각각 {MONTHLY_HEADLINE_MAX}자 이내여야 한다 (지금 {len(self.headlines)}개, 글자 수 {[len(h) for h in self.headlines]})")
        if not 2 <= len(self.trends) <= 3 or any(not t or len(t) > MONTHLY_TREND_MAX or not _ends_with_da(t) for t in self.trends):
            raise ValueError(f"trends는 2~3개이고 각각 {MONTHLY_TREND_MAX}자 이내이며 모든 문장이 ~다로 끝나야 한다 (지금 {len(self.trends)}개, 글자 수 {[len(t) for t in self.trends]})")
        picks = len(self.pick_ids)
        if not MONTHLY_PICKS_MIN <= picks <= MONTHLY_PICKS_MAX or len(set(self.pick_ids)) != picks or len(self.pick_reasons) != picks:
            raise ValueError(f"pick_ids는 겹치지 않는 {MONTHLY_PICKS_MIN}~{MONTHLY_PICKS_MAX}개이고 pick_reasons와 개수가 같아야 한다 (지금 ids {picks}개, reasons {len(self.pick_reasons)}개)")
        if any(not r or len(r) > MONTHLY_REASON_MAX or not _ends_with_da(r) for r in self.pick_reasons):
            raise ValueError(f"pick_reasons는 각각 {MONTHLY_REASON_MAX}자 이내이고 모든 문장이 ~다로 끝나야 한다 (글자 수 {[len(r) for r in self.pick_reasons]})")
        todos = len(self.todo_ids)
        if todos > MONTHLY_TODOS_MAX or len(set(self.todo_ids)) != todos or len(self.todo_texts) != todos:
            raise ValueError(f"todo_ids는 겹치지 않는 {MONTHLY_TODOS_MAX}개 이하이고 todo_texts와 개수가 같아야 한다 (지금 ids {todos}개, texts {len(self.todo_texts)}개)")
        if any(not t or len(t) > MONTHLY_TODO_MAX or not _ends_with_da(t) for t in self.todo_texts):
            raise ValueError(f"todo_texts는 각각 {MONTHLY_TODO_MAX}자 이내이고 모든 문장이 ~다로 끝나야 한다 (글자 수 {[len(t) for t in self.todo_texts]})")
        if _EXPERIENCE.search(self.body()):
            raise ValueError("써 보니, 써봤, 체감, 사용해 보니 같은 경험 표현을 쓰지 않는다")
        return self

    def body(self) -> str:
        """모델이 쓴 글(제목 후보, 흐름, 이유, 할 일 문장)을 이어 붙여 돌려준다."""
        return " ".join([*self.headlines, *self.trends, *self.pick_reasons, *self.todo_texts])


MONTHLY_SCHEMA = {
    "type": "object",
    "properties": MonthlyText.model_json_schema()["properties"],
    "required": ["headlines", "trends", "pick_ids", "pick_reasons", "todo_ids", "todo_texts"],
}


def _flat(text: str | None) -> str:
    """줄바꿈을 공백 하나로 줄여 한 줄로 만든다."""
    return " ".join((text or "").split())


def build_source(db: Session, month: date, stats: dict, today: date) -> tuple[str, dict[str, dict]]:
    """그 달의 숫자, 주요 항목, 곧 닿는 종료 일정을 모델에 보낼 글로 만든다.

    Args:
        db: DB 세션
        month: 그 달 1일
        stats: `monthly_crud.stats` 결과
        today: 종료 일정을 셀 기준 날짜(한국 시간)
    Returns:
        `(입력 글, ID별 화면 값)`. ID는 릴리스 항목 `R…`, 소식 `N…`, 종료 일정 `D…`이고 값은 `url` · `title` 또는 `date`다
    """
    refs: dict[str, dict] = {}
    lines = ["[집계]", json.dumps(stats, ensure_ascii=False, separators=(",", ":")), "[항목]"]
    for item, entry, source in monthly_crud.release_items(db, month, MONTHLY_ITEM_LIMIT):
        key, label = f"R{item.id}", release_label(source.name, entry.version or entry.title)
        refs[key] = {"url": release_path(source.slug, entry), "title": label}
        lines.append(f"- {key} | {label} | {item.category} | 중요도 {item.importance} | {_flat(item.summary_ko)}")
    for news in monthly_crud.news_items(db, month, MONTHLY_NEWS_LIMIT):
        key, title = f"N{news.id}", news.title_ko or news.title
        refs[key] = {"url": f"/news/{news.id}", "title": title}
        lines.append(f"- {key} | {news.company} | 중요도 {news.importance} | {_flat(title)} - {_flat(news.summary_ko)}")
    lines.append("[종료]")
    for row in deadline_crud.list_range(db, today, today + timedelta(days=MONTHLY_DEADLINE_DAYS), MONTHLY_DEADLINE_LIMIT):
        key = f"D{row.id}"
        refs[key] = {"date": row.deadline.isoformat()}
        lines.append(f"- {key} | {row.deadline.isoformat()} | {row.provider} | {row.name} | 대체: {row.replacement or '없음'}")
    return "\n".join(lines), refs


def parse(content: str, source: str, refs: dict[str, dict]) -> MonthlyText:
    """모델 답을 읽어 검증을 통과한 초안을 돌려준다.

    Args:
        content: 모델 답 본문
        source: 모델에 보낸 글
        refs: `build_source`가 만든 ID별 화면 값
    Returns:
        통과한 초안
    Raises:
        MonthlyRejected: JSON이 아니거나(`json`), 개수 · 길이 · 문장 끝이 틀렸거나(`schema`), 입력에 없는 ID(`id`) · 숫자(`number`) · 영어 단어(`words`)가 있을 때
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise MonthlyRejected("json", "JSON 형식이 아니다. 설명이나 코드 블록 없이 JSON 객체만 쓴다") from exc
    try:
        row = MonthlyText.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        reason = first["msg"].removeprefix("Value error, ")
        raise MonthlyRejected("schema", f"{where}: {reason}" if where else reason) from exc
    bad = [i for i in row.pick_ids if not i.startswith(("R", "N")) or i not in refs] + [i for i in row.todo_ids if not i.startswith("D") or i not in refs]
    if bad:
        raise MonthlyRejected("id", f"입력에 없거나 종류가 맞지 않는 ID를 썼다: {', '.join(bad)}. pick_ids는 R · N, todo_ids는 D로 시작하는 ID만 쓴다")
    body = row.body()
    known = {_plain_number(n) for n in _NUMBER.findall(source)}
    numbers = sorted({n for n in _NUMBER.findall(body) if _plain_number(n) not in known})
    if numbers:
        raise MonthlyRejected("number", f"입력에 없는 숫자를 썼다: {', '.join(numbers)}. 숫자는 입력에 있는 값만 그대로 쓰고 직접 계산하지 않는다")
    words = sorted(set(unseen_words(body, source)))
    if words:
        raise MonthlyRejected("words", f"입력에 없는 영어 단어나 일본어 · 한자를 썼다: {', '.join(words)}. 입력에 쓰인 이름과 용어만 쓴다")
    return row


def generate_month(db: Session, month: date, now: datetime) -> bool:
    """한 달의 월간 리포트 초안을 만들어 저장한다. 읽을 수 있는 답이 올 때까지 `LLM_MAX_RETRIES`번까지 다시 보내고(한 달에 최대 `LLM_MAX_RETRIES + 1`번), 호출마다 하루 한도를 확인하고 센다.

    거부된 답은 이유(`MonthlyRejected.hint`)와 함께 다음 시도에 돌려 보내 고치게 하고, 로그에는 이유 분류(`reason`)만 남긴다. 끝까지 통과하지 못하면 저장하지 않고 `MONTHLY_RETRY_HOURS`시간 동안 이 달을 건너뛰게 기록한 뒤 예외를 던진다.

    Args:
        db: DB 세션
        month: 그 달 1일
        now: 지금 시각
    Returns:
        저장했으면 `True`. 그 달 릴리스가 없어 만들지 않았으면 `False`
    Raises:
        lm_client.LlmRateLimited: 429를 받았을 때
        lm_client.LlmBudgetExhausted: 오늘 호출 한도를 다 썼을 때
        lm_client.LlmUnavailable: Gemini에 닿지 못했거나 끝까지 읽을 수 있는 답을 못 받았을 때
    """
    today = now.astimezone(KST).date()
    stats = monthly_crud.stats(db, month, today)
    if not stats["releases"]:
        return False
    source, refs = build_source(db, month, stats, today)
    base = [{"role": "system", "content": MONTHLY_PROMPT}, {"role": "user", "content": source}]
    messages, last = base, ""
    for attempt in range(settings.LLM_MAX_RETRIES + 1):
        if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
            raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
        llm_usage_crud.add_call(db, "gemini")
        completion = lm_client.complete(messages, MONTHLY_SCHEMA)
        try:
            row = parse(completion.content, source, refs)
        except MonthlyRejected as exc:
            last = exc.code
            log_event(llm_logger, event="monthly", provider="gemini", model=completion.model, refs=len(refs), ok=False, reason=exc.code, attempt=attempt + 1)
            feedback = f"위 답은 거부됐다. 이유: {exc.hint[:300]}. 규칙을 지켜 같은 형식의 JSON 객체로만 다시 답한다."
            messages = [*base, {"role": "assistant", "content": completion.content}, {"role": "user", "content": feedback}]
            continue
        log_event(llm_logger, event="monthly", provider="gemini", model=completion.model, refs=len(refs), ok=True, attempt=attempt + 1)
        draft = {
            "headlines": row.headlines,
            "trends": row.trends,
            "picks": [{"url": refs[i]["url"], "title": refs[i]["title"], "comment": r} for i, r in zip(row.pick_ids, row.pick_reasons)],
            "todos": [{"date": refs[i]["date"], "text": t} for i, t in zip(row.todo_ids, row.todo_texts)],
        }
        monthly_crud.save_draft(db, month, stats, draft, completion.model, MONTHLY_PROMPT_VERSION)
        db.commit()
        logger.info("monthly %s: 저장 (입력 %d개)", month, len(refs))
        return True
    _failed[month] = now
    raise LlmUnavailable(f"월간 리포트 초안 답을 읽지 못했습니다 (마지막 이유: {last})")


def finished_months(now: datetime) -> list[date]:
    """끝난 달의 1일을 최근 달부터 `MONTHLY_BACKFILL_MONTHS`개 돌려준다."""
    month = now.astimezone(KST).date().replace(day=1)
    months = []
    for _ in range(MONTHLY_BACKFILL_MONTHS):
        month = prev_month(month)
        months.append(month)
    return months


def generate_monthly_job() -> None:
    """스케줄러가 주기적으로 부르는 월간 리포트 초안 작업. 끝난 최근 몇 달 중 초안이 없는 달을 채운다. 요약 작업과 동시에 Gemini를 부르지 않게 `LLM_LOCK`을 잡는다.

    그 달에 요약을 기다리는 항목이 남아 있으면 `MONTHLY_PENDING_GRACE_DAYS`일까지는 기다리고, 답을 못 읽은 달은 `MONTHLY_RETRY_HOURS`시간 동안 건너뛴다. 429나 호출 한도 소진이면 Gemini를 쉬게 하고 끝낸다.
    """
    now = datetime.now(timezone.utc)
    with LLM_LOCK, SessionLocal() as db:
        for month in finished_months(now):
            try:
                failed = _failed.get(month)
                if monthly_crud.get_draft(db, month) is not None or monthly_crud.pending_count(db, month, now):
                    continue
                if failed and now - failed < timedelta(hours=MONTHLY_RETRY_HOURS):
                    continue
                if not gemini_ready(db):
                    break
                generate_month(db, month, now)
            except (LlmRateLimited, LlmBudgetExhausted) as exc:
                db.rollback()
                logger.warning("monthly: 쉼 (%s)", exc)
                block_gemini()
                break
            except LlmUnavailable as exc:
                db.rollback()
                logger.warning("monthly %s: 중단 (%s)", month, exc)
                break
            except Exception:
                db.rollback()
                logger.exception("monthly %s: 실패", month)