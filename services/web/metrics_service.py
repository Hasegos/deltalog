from collections.abc import Iterator

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from core.logger import get_logger
from crud import item_crud
from db.session import SessionLocal

logger = get_logger("metrics")

STATUSES = ("pending", "done", "failed")


class ItemStatusCollector(Collector):
    """`/metrics`를 읽을 때마다 요약 상태별 항목 수(`deltalog_items{status}`)를 DB에서 세어 내보낸다."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        """요약 상태별 항목 수 게이지를 만든다. DB를 읽지 못하면 이 지표만 빼고, `/metrics` 전체가 실패하지는 않게 한다.

        Returns:
            `deltalog_items` 게이지 하나 (조회에 실패하면 비어 있음)
        """
        try:
            with SessionLocal() as db:
                counts = item_crud.count_items_by_status(db)
        except Exception:
            logger.exception("metrics: 항목 수 조회 실패")
            return
        gauge = GaugeMetricFamily("deltalog_items", "요약 상태별 항목 수", labels=["status"])
        for status in STATUSES:
            gauge.add_metric([status], counts.get(status, 0))
        yield gauge