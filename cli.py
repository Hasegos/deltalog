import sys

from core.logger import setup_logging
from db.session import SessionLocal
from services.collector.poller_service import poll_all
from services.llm.llm_service import summarize_pending
from services.llm.lm_client import LlmUnavailable

USAGE = "사용법: python cli.py poll | python cli.py summarize [개수]"


def summarize(limit: int) -> None:
    """요약을 기다리는 항목을 최신 글부터 `limit`개 요약하고, 결과를 터미널에 보여준다.

    Args:
        limit: 처리할 최대 항목 수
    """
    with SessionLocal() as db:
        try:
            rows = summarize_pending(db, limit)
        except LlmUnavailable as exc:
            print(f"중단: {exc}")
            sys.exit(1)
    for item, entry, source in rows:
        head = f"{source.name} {entry.version or entry.title} #{item.seq}"
        if item.status == "done":
            print(f"[{head}] {item.category} · 중요도 {item.importance} · {item.topic or '-'}")
            print(f"  원문: {item.raw_text[:110]}")
            print(f"  요약: {item.summary_ko}")
        else:
            print(f"[{head}] 실패 ({item.error})")
    done = sum(1 for item, _, _ in rows if item.status == "done")
    print(f"\n처리 {len(rows)}건 · 완료 {done} · 실패 {len(rows) - done}")


def main() -> None:
    """터미널 명령을 실행한다. `poll`은 소스를 지금 한 번 가져오고, `summarize`는 요약을 기다리는 항목을 요약한다."""
    setup_logging()
    args = sys.argv[1:]
    if args == ["poll"]:
        print(f"새 글 {poll_all()}건")
    elif args[:1] == ["summarize"] and len(args) <= 2 and (len(args) == 1 or args[1].isdigit()):
        summarize(int(args[1]) if len(args) == 2 else 30)
    else:
        print(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main()