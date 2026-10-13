import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging() -> None:
    """루트 로거를 INFO 수준과 공통 형식으로 설정한다. 진입점(`main.py`, `cli.py`)에서 한 번 부른다."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """`deltalog.<name>` 이름의 로거를 돌려준다.

    Args:
        name: 로거 이름 (예: `poller`)
    Returns:
        로거
    """
    return logging.getLogger(f"deltalog.{name}")