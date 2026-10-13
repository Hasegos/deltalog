import logging
import sys

from services.poller_service import poll_all


def main() -> None:
    """터미널 명령을 실행한다. 지금은 `poll`(소스를 지금 한 번 가져오기)만 있다."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if sys.argv[1:] == ["poll"]:
        print(f"새 글 {poll_all()}건")
    else:
        print("사용법: python cli.py poll")
        sys.exit(2)


if __name__ == "__main__":
    main()