from collections.abc import Iterator

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from core.logger import get_logger
from crud import item_crud
from db.session import SessionLocal

logger = get_logger("metrics")

STATUSES = ("pending", "done", "failed")


class AppStateCollector(Collector):
    """`/metrics`를 읽을 때마다 DB를 읽어 요약 상태별 항목 수(`deltalog_items{status}`)와 소스별 마지막 수집 시각(`deltalog_source_last_polled_timestamp_seconds{source}`)을 내보낸다."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        """앱 상태 게이지를 만든다. DB를 읽지 못하면 이 지표들만 빼고, `/metrics` 전체가 실패하지는 않게 한다.

        Returns:
            `deltalog_items`, `deltalog_source_last_polled_timestamp_seconds` 게이지 (조회에 실패하면 비어 있음. 한 번도 수집하지 않은 소스는 빠진다)
        """
        try:
            with SessionLocal() as db:
                counts = item_crud.count_items_by_status(db)
                sources = item_crud.list_sources(db)
        except Exception:
            logger.exception("metrics: 앱 상태 조회 실패")
            return
        items = GaugeMetricFamily("deltalog_items", "요약 상태별 항목 수", labels=["status"])
        for status in STATUSES:
            items.add_metric([status], counts.get(status, 0))
        yield items
        polled = GaugeMetricFamily("deltalog_source_last_polled_timestamp_seconds", "소스를 마지막으로 가져온 시각 (Unix 초)", labels=["source"])
        for source in sources:
            if source.last_polled_at:
                polled.add_metric([source.slug], source.last_polled_at.timestamp())
        yield polled