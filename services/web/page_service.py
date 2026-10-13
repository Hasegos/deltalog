from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from core.constants.page import KST, SPARK_WEEKS
from core.constants.taxonomy import TOPICS
from crud import item_crud
from services.web.home_service import _week_start


def _week_starts(now: datetime) -> list[datetime]:
    """이번 주를 포함한 최근 몇 주의 월요일 00:00(한국 시간)을 오래된 순으로 돌려준다.

    Args:
        now: 기준 시각
    Returns:
        `SPARK_WEEKS`개의 주 시작 시각
    """
    this_week = _week_start(now)
    return [this_week - timedelta(weeks=n) for n in range(SPARK_WEEKS - 1, -1, -1)]


def _spark(times: list[datetime], starts: list[datetime]) -> dict:
    """게시 시각 목록을 주별 개수로 세어 스파크라인 값을 만든다.

    Args:
        times: 게시 시각 목록
        starts: 오래된 순의 주 시작 시각
    Returns:
        주별 개수 `counts`, 합계 `total`, SVG 꺾은선 좌표 `points`, 마지막 점 `last`
    """
    counts = [0] * len(starts)
    for t in times:
        t = t.astimezone(KST)
        for i in range(len(starts) - 1, -1, -1):
            if t >= starts[i]:
                counts[i] += 1
                break
    top = max(max(counts), 1)
    step = 92 / (len(counts) - 1)
    coords = [(round(2 + i * step, 1), round(22 - c / top * 20, 1)) for i, c in enumerate(counts)]
    return {
        "counts": counts,
        "total": sum(counts),
        "points": " ".join(f"{x},{y}" for x, y in coords),
        "last": coords[-1],
    }


def build_tools(db: Session, now: datetime | None = None) -> dict:
    """도구 목록 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
        now: 기준 시각. 비우면 현재 시각
    Returns:
        소스별 이름, 저장소 또는 사이트 주소(`sub`), 홈으로 가는 주소, 최근 몇 주의 릴리스 추이. 추이 합계가 큰 순서다
    """
    starts = _week_starts(now or datetime.now(KST))
    by_source = defaultdict(list)
    for source_id, published_at in item_crud.list_entry_times_since(db, starts[0]):
        by_source[source_id].append(published_at)

    tools = [
        {
            "name": s.name,
            "sub": s.repo or urlparse(s.feed_url or "").netloc,
            "href": f"/?tool={s.slug}",
            "spark": _spark(by_source[s.id], starts),
        }
        for s in item_crud.list_sources(db)
    ]
    tools.sort(key=lambda t: t["spark"]["total"], reverse=True)
    return {"weeks": SPARK_WEEKS, "tools": tools}


def build_topics(db: Session, now: datetime | None = None) -> dict:
    """주제 목록 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
        now: 기준 시각. 비우면 현재 시각
    Returns:
        주제별 이름, 항목 개수, 홈으로 가는 주소, 최근 몇 주의 항목 추이
    """
    starts = _week_starts(now or datetime.now(KST))
    by_topic = defaultdict(list)
    for topic, published_at in item_crud.list_topic_times_since(db, starts[0]):
        by_topic[topic].append(published_at)

    counts = item_crud.count_items_by_topic(db)
    return {
        "weeks": SPARK_WEEKS,
        "topics": [
            {
                "name": t,
                "count": counts.get(t, 0),
                "href": f"/?topic={t}",
                "spark": _spark(by_topic[t], starts),
            }
            for t in TOPICS
        ],
    }