from sqlalchemy.orm import Session

from core.constant import TOPICS
from crud import item_crud


def build_tools(db: Session) -> dict:
    """도구 목록 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
    Returns:
        소스별 이름, 종류, 항목 개수, 홈으로 가는 주소
    """
    counts = item_crud.count_items_by_source(db)
    return {
        "tools": [
            {"name": s.name, "kind": s.kind, "count": counts.get(s.id, 0), "href": f"/?tool={s.slug}"}
            for s in item_crud.list_sources(db)
        ]
    }


def build_topics(db: Session) -> dict:
    """주제 목록 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
    Returns:
        주제별 이름, 항목 개수, 홈으로 가는 주소
    """
    counts = item_crud.count_items_by_topic(db)
    return {"topics": [{"name": t, "count": counts.get(t, 0), "href": f"/?topic={t}"} for t in TOPICS]}