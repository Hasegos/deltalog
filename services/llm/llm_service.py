import json
import re
from itertools import groupby
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.llm import BATCH_SIZE, MAX_ITEM_CHARS, PROMPT_VERSION
from core.constants.prompts import SYSTEM_PROMPT
from core.constants.taxonomy import TOPICS
from core.logger import get_logger
from crud import item_crud
from models.entry_model import Entry
from models.item_model import Item
from models.source_model import Source
from services.llm import lm_client

logger = get_logger("summarizer")


class Summary(BaseModel):
    """모델이 항목 하나에 대해 돌려주는 값."""

    n: int
    category: Literal["feature", "bugfix", "breaking", "security", "other"]
    topic: str = ""
    importance: int = Field(ge=1, le=5)
    summary_ko: str = Field(min_length=1)


SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": Summary.model_json_schema()}},
    "required": ["items"],
}


def _messages(source: Source, entry: Entry, texts: dict[int, str]) -> list[dict]:
    """모델에 보낼 메시지를 만든다.

    Args:
        source: 소스
        entry: 글(릴리스)
        texts: 번호별 항목 원문
    Returns:
        시스템과 사용자 메시지 목록
    """
    lines = "\n".join(f"{n}. {text[:MAX_ITEM_CHARS]}" for n, text in texts.items())
    user = f"도구: {source.name}\n버전: {entry.version or entry.title}\n\n{lines}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _parse(content: str, wanted: set[int]) -> dict[int, Summary]:
    """모델 답을 읽어 검증을 통과한 항목만 번호별로 돌려준다. 통과하지 못한 항목은 들어 있지 않다.

    Args:
        content: 모델 답 본문
        wanted: 기다리는 번호
    Returns:
        번호별 검증된 값. 주제가 목록에 없으면 빈 값으로 바꾼다
    """
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    try:
        raw_items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return {}

    result: dict[int, Summary] = {}
    for raw in raw_items if isinstance(raw_items, list) else []:
        try:
            summary = Summary.model_validate(raw)
        except ValidationError:
            continue
        if summary.n in wanted and summary.n not in result:
            if summary.topic not in TOPICS:
                summary.topic = ""
            result[summary.n] = summary
    return result


def summarize_batch(source: Source, entry: Entry, items: list[Item]) -> None:
    """같은 릴리스의 항목 몇 개를 한 번에 요약해 결과를 항목에 채운다. 커밋은 부르는 쪽이 한다.

    검증에 실패한 항목만 `LLM_MAX_RETRIES`번까지 다시 보내고, 그래도 안 되면 `failed`로 둔다.

    Args:
        source: 소스
        entry: 글(릴리스)
        items: 같은 글에 속한 항목들
    Raises:
        lm_client.LlmUnavailable: LM Studio에 닿지 못했을 때. 이때 항목 상태는 바꾸지 않는다
    """
    waiting = {n: item for n, item in enumerate(items, start=1)}
    for _ in range(settings.LLM_MAX_RETRIES + 1):
        if not waiting:
            break
        content = lm_client.complete(_messages(source, entry, {n: i.raw_text for n, i in waiting.items()}), SCHEMA)
        for n, summary in _parse(content, set(waiting)).items():
            item = waiting.pop(n)
            item.category = summary.category
            item.topic = summary.topic or None
            item.importance = summary.importance
            item.summary_ko = summary.summary_ko
            item.status = "done"
            item.model = settings.LM_STUDIO_MODEL
            item.prompt_version = PROMPT_VERSION
            item.error = None

    for item in waiting.values():
        item.status = "failed"
        item.model = settings.LM_STUDIO_MODEL
        item.prompt_version = PROMPT_VERSION
        item.error = "검증 실패 (재시도 횟수 초과)"


def summarize_pending(db: Session, limit: int) -> list[tuple[Item, Entry, Source]]:
    """요약을 기다리는 항목을 최신 글부터 `limit`개까지 요약한다. 묶음마다 커밋해서 중간에 멈춰도 결과가 남는다.

    Args:
        db: DB 세션
        limit: 처리할 최대 항목 수
    Returns:
        처리한 `(항목, 글, 소스)` 목록. 항목의 `status`가 `done` 또는 `failed`다
    Raises:
        lm_client.LlmUnavailable: LM Studio에 닿지 못했을 때. 그때까지 끝낸 묶음은 저장돼 있다
    """
    rows = item_crud.list_pending_items(db, limit)
    processed: list[tuple[Item, Entry, Source]] = []
    for _, group in groupby(rows, key=lambda row: row[1].id):
        group_rows = list(group)
        entry, source = group_rows[0][1], group_rows[0][2]
        for start in range(0, len(group_rows), BATCH_SIZE):
            batch = group_rows[start : start + BATCH_SIZE]
            summarize_batch(source, entry, [row[0] for row in batch])
            db.commit()
            processed.extend(batch)
            logger.info(
                "summarize %s %s: %d건 처리 (완료 %d, 실패 %d)",
                source.slug,
                entry.version or entry.id,
                len(batch),
                sum(1 for row in batch if row[0].status == "done"),
                sum(1 for row in batch if row[0].status == "failed"),
            )
    return processed