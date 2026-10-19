import json
import re
from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError, model_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.deadline import (
    DEADLINE_KINDS,
    DEADLINE_PAST_DAYS,
    DEADLINE_PROMPT_VERSION,
    DEADLINE_SOURCES,
    DEADLINE_SUMMARY_MAX,
)
from core.constants.page import KST
from core.constants.prompts import DEADLINE_PROMPT
from core.logger import get_logger, log_event
from crud import deadline_crud, llm_usage_crud
from db.session import SessionLocal
from models.deadline_model import Deadline
from services.collector import deadline_service, status_service
from services.llm import lm_client
from services.llm.lm_client import LlmBudgetExhausted, LlmRateLimited, LlmUnavailable
from services.llm.llm_service import LLM_LOCK, block_gemini, gemini_ready, unseen_words

logger = get_logger("deadline")
llm_logger = get_logger("llm")


def _day(value: str) -> date | None:
    """`YYYY-MM-DD` 글을 날짜로 바꾼다. 형식이 틀리거나 없는 날짜면 `None`이다."""
    try:
        return date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None
    except ValueError:
        return None


def appears(day: date, text: str) -> bool:
    """문서 조각에 그 날짜가 글로 적혀 있는지 본다 (`2026-10-14`, `October 14, 2026`, `Oct 14, 2026`, `14 October 2026`).

    모델이 지어낸 날짜를 걸러내는 데 쓴다.

    Args:
        day: 확인할 날짜
        text: 문서 조각
    Returns:
        한 가지 표기라도 있으면 `True`
    """
    forms = (
        day.isoformat(),
        f"{day:%B} {day.day}, {day.year}",
        f"{day:%b} {day.day}, {day.year}",
        f"{day:%b}. {day.day}, {day.year}",
        f"{day.day} {day:%B} {day.year}",
        f"{day.day} {day:%b} {day.year}",
    )
    return any(form in text for form in forms)


class DeadlineRow(BaseModel):
    """모델이 문서 조각에서 뽑아 돌려주는 종료 일정 하나."""

    name: str
    kind: Literal[tuple(DEADLINE_KINDS)]
    deadline: str
    deprecated_on: str
    replacement: str
    summary_ko: str

    @model_validator(mode="after")
    def check(self) -> "DeadlineRow":
        """공백과 NUL 문자를 다듬고, 종료일 형식, 요약이 "~다"로 끝나는지, 길이를 확인한다.

        Returns:
            다듬은 값
        Raises:
            ValueError: 이름이 비었거나, 종료일이 날짜가 아니거나, 요약이 규칙에 맞지 않을 때
        """
        for field in ("name", "deadline", "deprecated_on", "replacement", "summary_ko"):
            setattr(self, field, getattr(self, field).replace("\x00", "").strip())
        if not self.name:
            raise ValueError("이름 없음")
        if _day(self.deadline) is None:
            raise ValueError(f"종료일 형식 오류({self.deadline})")
        if self.deprecated_on and _day(self.deprecated_on) is None:
            self.deprecated_on = ""
        summary = self.summary_ko.rstrip(".").strip()
        if not summary.endswith("다") or len(summary) > DEADLINE_SUMMARY_MAX or re.search(r"\d{4}년|\d{1,2}월|\d{1,2}일", summary):
            raise ValueError("요약 형식 오류")
        self.summary_ko = summary
        return self


DEADLINE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": DeadlineRow.model_json_schema()}},
    "required": ["items"],
}


def _messages(chunk: str, today: date) -> list[dict]:
    """모델에 보낼 메시지를 만든다."""
    return [{"role": "system", "content": DEADLINE_PROMPT.replace("@@TODAY@@", today.isoformat())}, {"role": "user", "content": chunk}]


def parse(content: str, chunk: str, today: date) -> list[DeadlineRow] | None:
    """모델 답을 읽어 검증을 통과한 일정만 돌려준다.

    검증: 형식, 종료일이 문서 조각에 글로 적혀 있는지, 이름이 문서 조각에 있는지, 종료일이 오늘보다 `DEADLINE_PAST_DAYS`일 넘게 지나지 않았는지, 요약에 원문에 없는 영어가 없는지.

    Args:
        content: 모델 답 본문
        chunk: 보낸 문서 조각
        today: 오늘 날짜
    Returns:
        통과한 일정. 답이 JSON이 아니면 `None`
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        raw_items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return None
    lowered = chunk.lower()
    oldest = today - timedelta(days=DEADLINE_PAST_DAYS)
    found: list[DeadlineRow] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        try:
            row = DeadlineRow.model_validate(raw)
        except ValidationError:
            continue
        day = _day(row.deadline)
        if day < oldest or not appears(day, chunk) or row.name.lower() not in lowered:
            continue
        if unseen_words(row.summary_ko, chunk):
            continue
        found.append(row)
    return found


def extract_chunk(db: Session, chunk: str, today: date) -> list[DeadlineRow]:
    """문서 조각 하나에서 종료 일정을 뽑는다. 답이 JSON이 아니면 `LLM_MAX_RETRIES`번까지 다시 보낸다. 호출마다 하루 한도를 확인하고 센다.

    Args:
        db: DB 세션
        chunk: 문서 조각
        today: 오늘 날짜
    Returns:
        검증을 통과한 일정
    Raises:
        lm_client.LlmRateLimited: 429를 받았을 때
        lm_client.LlmBudgetExhausted: 오늘 호출 한도를 다 썼을 때
        lm_client.LlmUnavailable: Gemini에 닿지 못했거나 끝까지 읽을 수 있는 답을 못 받았을 때
    """
    for attempt in range(settings.LLM_MAX_RETRIES + 1):
        if llm_usage_crud.calls_today(db, "gemini") >= settings.GEMINI_DAILY_LIMIT:
            raise LlmBudgetExhausted("Gemini 오늘 호출 한도를 모두 썼습니다")
        llm_usage_crud.add_call(db, "gemini")
        completion = lm_client.complete(_messages(chunk, today), DEADLINE_SCHEMA)
        rows = parse(completion.content, chunk, today)
        log_event(llm_logger, event="deadline_chunk", provider="gemini", model=completion.model, chars=len(chunk), rows=-1 if rows is None else len(rows), attempt=attempt + 1)
        if rows is not None:
            return rows
    raise LlmUnavailable("종료 일정 답을 읽지 못했습니다")


def refresh_source(db: Session, source: dict) -> int:
    """종료 일정 문서 하나를 받아 내용이 바뀌었으면(또는 프롬프트 버전이 바뀌었으면) 일정을 새로 뽑아 저장한다.

    조각마다 Gemini를 부르고, 모두 끝난 뒤에 한꺼번에 저장한다. 중간에 멈추면 아무것도 저장하지 않아 다음 실행이 처음부터 다시 한다.

    Args:
        db: DB 세션
        source: `DEADLINE_SOURCES`의 한 줄
    Returns:
        새로 더한 일정 개수. 문서가 바뀌지 않았으면 0
    Raises:
        httpx.HTTPError: 문서를 받지 못했을 때
        lm_client.LlmUnavailable: Gemini를 쓰지 못했을 때 (`LlmRateLimited`, `LlmBudgetExhausted` 포함)
    """
    text = deadline_service.fetch_text(source["url"])
    digest = deadline_service.content_hash(text)
    page = deadline_crud.get_page(db, source["slug"])
    if page is not None and page.content_hash == digest and page.prompt_version == DEADLINE_PROMPT_VERSION:
        deadline_crud.save_page(db, source["slug"], digest, DEADLINE_PROMPT_VERSION, extracted=False)
        db.commit()
        return 0
    if not gemini_ready(db):
        raise LlmUnavailable("Gemini를 지금 쓸 수 없습니다")
    today = datetime.now(KST).date()
    rows: dict[tuple[str, str], DeadlineRow] = {}
    for chunk in deadline_service.chunks(text):
        for row in extract_chunk(db, chunk, today):
            rows.setdefault((row.name, row.deadline), row)
        db.commit()
    added = deadline_crud.upsert(
        db,
        source["provider"],
        [
            Deadline(
                provider=source["provider"],
                name=row.name,
                kind=row.kind,
                deadline=date.fromisoformat(row.deadline),
                deprecated_on=date.fromisoformat(row.deprecated_on) if row.deprecated_on else None,
                replacement=row.replacement or None,
                summary_ko=row.summary_ko,
                source_url=source["url"],
                source_slug=source["slug"],
                prompt_version=DEADLINE_PROMPT_VERSION,
            )
            for row in rows.values()
        ],
    )
    deadline_crud.save_page(db, source["slug"], digest, DEADLINE_PROMPT_VERSION, extracted=True)
    db.commit()
    logger.info("deadline %s: 일정 %d건 (새로 %d건)", source["slug"], len(rows), added)
    return added


def refresh_deadlines_job() -> None:
    """스케줄러가 주기적으로 부르는 종료 일정 갱신 작업. 요약 작업과 동시에 Gemini를 부르지 않게 `LLM_LOCK`을 잡는다.

    문서마다 하나씩 처리하고, 문서를 못 받은 곳은 경고만 남기고 다음으로 넘어간다. 429나 호출 한도 소진이면 Gemini를 쉬게 하고 끝낸다.
    """
    with LLM_LOCK, SessionLocal() as db:
        for source in DEADLINE_SOURCES:
            label = f"{source['provider']} 종료 일정 문서"
            try:
                refresh_source(db, source)
                status_service.record(source["slug"], label, "deadline", True)
            except httpx.HTTPError as exc:
                db.rollback()
                logger.warning("deadline %s: 문서를 받지 못함 (%s)", source["slug"], exc.__class__.__name__)
                status_service.record(source["slug"], label, "deadline", False, exc.__class__.__name__)
            except (LlmRateLimited, LlmBudgetExhausted) as exc:
                db.rollback()
                logger.warning("deadline: 쉼 (%s)", exc)
                block_gemini()
                break
            except LlmUnavailable as exc:
                db.rollback()
                logger.warning("deadline %s: 중단 (%s)", source["slug"], exc)
                break
            except Exception as exc:
                db.rollback()
                logger.exception("deadline %s: 실패", source["slug"])
                status_service.record(source["slug"], label, "deadline", False, exc.__class__.__name__)