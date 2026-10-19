import json
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ValidationError, model_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.page import KST
from core.constants.prompts import WEEKLY_PROMPT
from core.constants.weekly import (
    WEEKLY_BACKFILL_WEEKS,
    WEEKLY_HEADLINE_MAX,
    WEEKLY_MIN_LINES,
    WEEKLY_NEWS_LIMIT,
    WEEKLY_NEWS_MIN,
    WEEKLY_OVERVIEW_MAX,
    WEEKLY_OVERVIEW_MIN,
    WEEKLY_PENDING_GRACE_DAYS,
    WEEKLY_PROMPT_VERSION,
    WEEKLY_RELEASE_LIMIT,
    WEEKLY_RELEASE_MIN,
)
from core.logger import get_logger, log_event
from core.weeks import monday_of, week_bounds
from crud import llm_usage_crud, weekly_crud
from db.session import SessionLocal
from services.llm import lm_client
from services.llm.lm_client import LlmBudgetExhausted, LlmRateLimited, LlmUnavailable
from services.llm.llm_service import LLM_LOCK, block_gemini, gemini_ready, unseen_words

logger = get_logger("weekly")
llm_logger = get_logger("llm")


class WeeklyText(BaseModel):
    """모델이 돌려주는 주간 요약의 제목과 개요."""

    headline: str
    overview: str

    @model_validator(mode="after")
    def check(self) -> "WeeklyText":
        """공백과 NUL 문자를 다듬고 길이, 문장 끝 형식을 확인한다.

        Returns:
            다듬은 값
        Raises:
            ValueError: 제목이 길거나, 개요가 길이 범위 밖이거나, 문장이 "~다"로 끝나지 않을 때
        """
        self.headline = self.headline.replace("\x00", "").strip().rstrip(".")
        self.overview = self.overview.replace("\x00", "").strip()
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", self.overview) if s]
        if not self.headline or len(self.headline) > WEEKLY_HEADLINE_MAX:
            raise ValueError("제목 길이 오류")
        if not WEEKLY_OVERVIEW_MIN <= len(self.overview) <= WEEKLY_OVERVIEW_MAX or any(not s.rstrip(".").endswith("다") for s in sentences):
            raise ValueError("개요 형식 오류")
        return self


WEEKLY_SCHEMA = {"type": "object", "properties": WeeklyText.model_json_schema()["properties"], "required": ["headline", "overview"]}


def source_lines(db: Session, monday) -> list[str]:
    """그 주의 주요 릴리스와 소식을 모델에 보낼 줄로 만든다.

    Args:
        db: DB 세션
        monday: 그 주 월요일
    Returns:
        `- [릴리스] ...` 또는 `- [소식] ...` 줄 목록
    """
    start, end = week_bounds(monday)
    lines = [
        f"- [릴리스] {source.name} {entry.version or entry.title} (중요도 {item.importance}): {item.summary_ko}"
        for item, entry, source in weekly_crud.release_items(db, start, end, WEEKLY_RELEASE_MIN, WEEKLY_RELEASE_LIMIT)
    ]
    lines += [
        f"- [소식] {news.company} (중요도 {news.importance}): {news.title_ko or news.title} - {news.summary_ko or ''}"
        for news in weekly_crud.news_items(db, start, end, WEEKLY_NEWS_MIN, WEEKLY_NEWS_LIMIT)
    ]
    return lines


def parse(content: str, source: str) -> WeeklyText | None:
    """모델 답을 읽어 검증을 통과한 제목과 개요를 돌려준다. 형식이 틀리거나 입력에 없는 영어 단어가 있으면 `None`이다.

    Args:
        content: 모델 답 본문
        source: 모델에 보낸 줄들(이어 붙인 글)
    Returns:
        통과한 제목과 개요. 아니면 `None`
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        row = WeeklyText.model_validate(json.loads(text))
    except (ValueError, TypeError, ValidationError):
        return None
    return None if unseen_words(f"{row.headline} {row.overview}", source) else row


def generate_week(db: Session, monday) -> bool:
    """한 주의 주간 요약을 만들어 저장한다. 읽을 수 있는 답이 올 때까지 `LLM_MAX_RETRIES`번까지 다시 보낸다. 호출마다 하루 한도를 확인하고 센다.

    Args:
        db: DB 세션
        monday: 그 주 월요일
    Returns:
        저장했으면 `True`. 줄이 `WEEKLY_MIN_LINES`개 미만이라 만들지 않았으면 `False`
    Raises:
        lm_client.LlmRateLimited: 429를 받았을 때
        lm_client.LlmBudgetExhausted: 오늘 호출 한도를 다 썼을 때
        lm_client.LlmUnavailable: Gemini에 닿지 못했거나 끝까지 읽을 수 있는 답을 못 받았을 때
    """
    lines = source_lines(db, monday)
    if len(lines) < WEEKLY_MIN_LINES:
        return False
    source = "\n".join(lines)
    messages = [{"role": "system", "content": WEEKLY_PROMPT}, {"role": "user", "content": source}]
    for attempt in range(settings.LLM_MAX_RETRIES + 1):
        if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
            raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
        llm_usage_crud.add_call(db, "gemini")
        completion = lm_client.complete(messages, WEEKLY_SCHEMA)
        row = parse(completion.content, source)
        log_event(llm_logger, event="weekly", provider="gemini", model=completion.model, lines=len(lines), ok=row is not None, attempt=attempt + 1)
        if row is not None:
            weekly_crud.save(db, monday, row.headline, row.overview, completion.model, WEEKLY_PROMPT_VERSION)
            db.commit()
            logger.info("weekly %s: 저장 (줄 %d개)", monday, len(lines))
            return True
    raise LlmUnavailable("주간 요약 답을 읽지 못했습니다")


def finished_weeks(now: datetime) -> list:
    """끝난 주의 월요일을 최근 주부터 `WEEKLY_BACKFILL_WEEKS`개 돌려준다."""
    this_monday = monday_of(now.astimezone(KST).date())
    return [this_monday - timedelta(weeks=n) for n in range(1, WEEKLY_BACKFILL_WEEKS + 1)]


def generate_weekly_job() -> None:
    """스케줄러가 주기적으로 부르는 주간 요약 작업. 끝난 최근 몇 주 중 요약이 없는 주를 채운다. 요약 작업과 동시에 Gemini를 부르지 않게 `LLM_LOCK`을 잡는다.

    그 주에 요약을 기다리는 항목이 남아 있으면 `WEEKLY_PENDING_GRACE_DAYS`일까지는 기다린다. 429나 호출 한도 소진이면 Gemini를 쉬게 하고 끝낸다.
    """
    now = datetime.now(timezone.utc)
    with LLM_LOCK, SessionLocal() as db:
        for monday in finished_weeks(now):
            try:
                if weekly_crud.get(db, monday) is not None:
                    continue
                start, end = week_bounds(monday)
                if now < end + timedelta(days=WEEKLY_PENDING_GRACE_DAYS) and weekly_crud.count_pending(db, start, end):
                    continue
                if not gemini_ready(db):
                    break
                generate_week(db, monday)
            except (LlmRateLimited, LlmBudgetExhausted) as exc:
                db.rollback()
                logger.warning("weekly: 쉼 (%s)", exc)
                block_gemini()
                break
            except LlmUnavailable as exc:
                db.rollback()
                logger.warning("weekly %s: 중단 (%s)", monday, exc)
                break
            except Exception:
                db.rollback()
                logger.exception("weekly %s: 실패", monday)