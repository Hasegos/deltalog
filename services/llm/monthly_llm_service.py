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

_QUOTES = ('"', "“", "”")
_EXPERIENCE = re.compile(r"써 보니|써봤|체감|사용해 보니")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_failed: dict[date, datetime] = {}


def _clean(texts: list[str]) -> list[str]:
    """글마다 NUL 문자를 지우고 앞뒤 공백을 뗀다."""
    return [t.replace("\x00", "").strip() for t in texts]


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
        """공백과 NUL 문자를 다듬고 개수 · 길이 · 문장 끝 · 따옴표 · 경험 표현을 확인한다.

        Returns:
            다듬은 값
        Raises:
            ValueError: 개수나 길이가 맞지 않거나, 문장이 "~다"로 끝나지 않거나, 큰따옴표나 경험 표현(써 보니, 체감 등)이 있을 때
        """
        self.headlines = [h.rstrip(".") for h in _clean(self.headlines)]
        self.trends, self.pick_reasons, self.todo_texts = _clean(self.trends), _clean(self.pick_reasons), _clean(self.todo_texts)
        self.pick_ids, self.todo_ids = _clean(self.pick_ids), _clean(self.todo_ids)
        if len(self.headlines) != 3 or any(not h or len(h) > MONTHLY_HEADLINE_MAX for h in self.headlines):
            raise ValueError("제목 후보 오류")
        if not 2 <= len(self.trends) <= 3 or any(not t or len(t) > MONTHLY_TREND_MAX or not _ends_with_da(t) for t in self.trends):
            raise ValueError("흐름 문단 오류")
        picks = len(self.pick_ids)
        if not MONTHLY_PICKS_MIN <= picks <= MONTHLY_PICKS_MAX or len(set(self.pick_ids)) != picks or len(self.pick_reasons) != picks:
            raise ValueError("고른 변경 개수 오류")
        if any(not r or len(r) > MONTHLY_REASON_MAX or not _ends_with_da(r) for r in self.pick_reasons):
            raise ValueError("고른 이유 형식 오류")
        todos = len(self.todo_ids)
        if todos > MONTHLY_TODOS_MAX or len(set(self.todo_ids)) != todos or len(self.todo_texts) != todos:
            raise ValueError("할 일 개수 오류")
        if any(not t or len(t) > MONTHLY_TODO_MAX or not _ends_with_da(t) for t in self.todo_texts):
            raise ValueError("할 일 형식 오류")
        body = self.body()
        if any(q in body for q in _QUOTES) or _EXPERIENCE.search(body):
            raise ValueError("따옴표나 경험 표현 오류")
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


def parse(content: str, source: str, refs: dict[str, dict]) -> MonthlyText | None:
    """모델 답을 읽어 검증을 통과한 초안을 돌려준다. 형식이 틀리거나 입력에 없는 ID · 숫자 · 영어 단어가 있으면 `None`이다.

    Args:
        content: 모델 답 본문
        source: 모델에 보낸 글
        refs: `build_source`가 만든 ID별 화면 값
    Returns:
        통과한 초안. 아니면 `None`
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        row = MonthlyText.model_validate(json.loads(text))
    except (ValueError, TypeError, ValidationError):
        return None
    if any(not i.startswith(("R", "N")) or i not in refs for i in row.pick_ids) or any(not i.startswith("D") or i not in refs for i in row.todo_ids):
        return None
    body = row.body()
    known = {_plain_number(n) for n in _NUMBER.findall(source)}
    if any(_plain_number(n) not in known for n in _NUMBER.findall(body)) or unseen_words(body, source):
        return None
    return row


def generate_month(db: Session, month: date, now: datetime) -> bool:
    """한 달의 월간 리포트 초안을 만들어 저장한다. 읽을 수 있는 답이 올 때까지 `LLM_MAX_RETRIES`번까지 다시 보내고(한 달에 최대 `LLM_MAX_RETRIES + 1`번), 호출마다 하루 한도를 확인하고 센다.

    끝까지 통과하지 못하면 저장하지 않고 `MONTHLY_RETRY_HOURS`시간 동안 이 달을 건너뛰게 기록한 뒤 예외를 던진다.

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
    messages = [{"role": "system", "content": MONTHLY_PROMPT}, {"role": "user", "content": source}]
    for attempt in range(settings.LLM_MAX_RETRIES + 1):
        if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
            raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
        llm_usage_crud.add_call(db, "gemini")
        completion = lm_client.complete(messages, MONTHLY_SCHEMA)
        row = parse(completion.content, source, refs)
        log_event(llm_logger, event="monthly", provider="gemini", model=completion.model, refs=len(refs), ok=row is not None, attempt=attempt + 1)
        if row is not None:
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
    raise LlmUnavailable("월간 리포트 초안 답을 읽지 못했습니다")


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