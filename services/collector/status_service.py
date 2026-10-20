import httpx

from core.config import settings
from core.constants.source import SOURCES
from core.logger import get_logger
from crud import feed_status_crud
from db.session import SessionLocal

logger = get_logger("status")
RELEASE_SLUGS = {source["slug"] for source in SOURCES}


def notify(text: str) -> None:
    """`ALERT_WEBHOOK_URL`이 있으면 그곳으로 알림을 보낸다. Discord(`content`)와 Slack(`text`) 웹훅 모두 받는 형태이고, 실패해도 예외를 내지 않는다.

    Args:
        text: 알림 글
    """
    if not settings.ALERT_WEBHOOK_URL:
        return
    try:
        httpx.post(settings.ALERT_WEBHOOK_URL, json={"content": text, "text": text}, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("알림 전송 실패 (%s)", exc.__class__.__name__)


def record(slug: str, label: str, group: str, ok: bool, error: str | None = None) -> None:
    """수집 한 번의 결과를 기록하고, 연속 실패가 기준에 이르거나 복구되면 알림을 보낸다. 기록에 실패해도 수집을 막지 않는다.

    Args:
        slug: 수집 대상 slug
        label: 화면에 보일 이름
        group: 묶음 (`release`, `news`, `deadline`)
        ok: 성공했는지
        error: 실패했을 때 오류 종류 이름
    """
    # 현황 행은 slug 하나가 키라서, 릴리스 소스와 같은 slug를 쓰는 소식 · 종료 일정 문서(`openai-api`)는 키를 나눈다
    key = f"{group}-{slug}" if group != "release" and slug in RELEASE_SLUGS else slug
    try:
        with SessionLocal() as db:
            event = feed_status_crud.record(db, key, label, group, ok, error)
            db.commit()
    except Exception:
        logger.exception("수집 현황 기록 실패: %s", slug)
        return
    if event == "down":
        notify(f"[Deltalog] {label} 수집이 연속으로 실패하고 있습니다 ({error or '알 수 없음'}). 확인이 필요합니다.")
    elif event == "up":
        notify(f"[Deltalog] {label} 수집이 복구됐습니다.")