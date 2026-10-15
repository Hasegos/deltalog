import json
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from core.config import settings
from core.constants.page import KST

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")


class DailyFileHandler(logging.Handler):
    """`<LOG_DIR>/<날짜(KST)>/<파일 이름>`에 한 줄씩 덧붙인다. 날짜가 바뀌면 새 폴더에 쓴다."""

    def __init__(self, filename: str) -> None:
        """
        Args:
            filename: 날짜 폴더 안의 파일 이름 (예: `app.log`)
        """
        super().__init__()
        self.filename = filename

    def emit(self, record: logging.LogRecord) -> None:
        """기록 한 건을 오늘 날짜 폴더의 파일에 쓴다.

        Args:
            record: 기록
        """
        try:
            path = Path(settings.LOG_DIR) / datetime.now(KST).strftime("%Y-%m-%d") / self.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as file:
                file.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)


def setup_logging() -> None:
    """로깅을 설정한다. 진입점(`main.py`)에서 한 번 부른다.

    - 터미널과 `app.log`: 루트 로거(INFO). 앱, 수집, 요약 진행, 스케줄러, uvicorn 시작 · 오류
    - `api.log`: `deltalog.api` 로거 전용. HTTP 요청 1건당 JSON 한 줄
    - `llm.log`: `deltalog.llm` 로거 전용. LM Studio 호출 JSON 한 줄
    """
    formatter = logging.Formatter(LOG_FORMAT)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    app_file = DailyFileHandler("app.log")
    app_file.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stream, app_file]

    uvicorn = logging.getLogger("uvicorn")
    uvicorn.handlers = [h for h in uvicorn.handlers if not isinstance(h, DailyFileHandler)] + [app_file]
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)

    for name, filename in (("deltalog.api", "api.log"), ("deltalog.llm", "llm.log")):
        file_handler = DailyFileHandler(filename)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.handlers = [file_handler]


def get_logger(name: str) -> logging.Logger:
    """`deltalog.<name>` 이름의 로거를 돌려준다.

    Args:
        name: 로거 이름 (예: `poller`)
    Returns:
        로거
    """
    return logging.getLogger(f"deltalog.{name}")


def log_event(logger: logging.Logger, **fields: object) -> None:
    """시각(`ts`, KST)과 값들을 JSON 한 줄로 남긴다. `api.log`, `llm.log`용이다.

    Args:
        logger: 기록할 로거
        **fields: 남길 값
    """
    logger.info(json.dumps({"ts": datetime.now(KST).isoformat(timespec="seconds"), **fields}, ensure_ascii=False))


def purge_old_logs() -> None:
    """`LOG_RETENTION_DAYS`보다 오래된 날짜 폴더를 지운다. 날짜 이름이 아닌 폴더는 건드리지 않는다."""
    root = Path(settings.LOG_DIR)
    if not root.is_dir():
        return
    limit = (datetime.now(KST) - timedelta(days=settings.LOG_RETENTION_DAYS)).strftime("%Y-%m-%d")
    for folder in root.iterdir():
        if folder.is_dir() and DATE_DIR.fullmatch(folder.name) and folder.name < limit:
            shutil.rmtree(folder, ignore_errors=True)