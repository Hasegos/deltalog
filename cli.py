import sys
from datetime import datetime

from core.constants.page import KST
from core.logger import setup_logging
from db.session import SessionLocal
from services.collector.poller_service import poll_all
from services.llm.llm_service import pick_provider, summarize_pending
from services.llm.lm_client import LlmUnavailable
from services.log_service import day_stats

USAGE = "사용법: python cli.py poll | python cli.py summarize [개수] | python cli.py stats [YYYY-MM-DD]"


def summarize(limit: int) -> None:
    """요약을 기다리는 항목을 최신 글부터 `limit`개 요약하고, 결과를 터미널에 보여준다.

    Args:
        limit: 처리할 최대 항목 수
    """
    with SessionLocal() as db:
        try:
            provider = pick_provider(db)
            if provider is None:
                print("중단: 쓸 수 있는 제공자가 없습니다 (Gemini 한도 소진 또는 대기 중)")
                sys.exit(1)
            rows = summarize_pending(db, limit, provider)
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


def stats(day: str) -> None:
    """하루치 접속 로그(`api.log`)와 LLM 호출 로그(`llm.log`)를 집계해 보여준다.

    Args:
        day: `YYYY-MM-DD`
    """
    result = day_stats(day)
    api, llm = result["api"], result["llm"]
    print(f"[{day}] 요청 {api['requests']}건 · 접속자(IP) {api['visitors']}명")
    print("  IP별: " + ", ".join(f"{ip} {n}" for ip, n in api["by_ip"]))
    print("  경로별: " + ", ".join(f"{path} {n}" for path, n in api["by_path"]))
    print("  상태별: " + ", ".join(f"{code} {n}" for code, n in api["by_status"]))
    print(f"[{day}] LLM 호출 {llm['calls']}회 (성공 {llm['ok']} · 실패 {llm['failed']}) · 평균 {llm['avg_ms']}ms")
    print(f"  토큰: 입력 {llm['prompt_tokens']} · 출력 {llm['completion_tokens']}")
    print(f"  요약 묶음 {llm['batches']}개 · 항목 완료 {llm['items_done']} · 실패 {llm['items_failed']}")


def main() -> None:
    """터미널 명령을 실행한다. `poll`은 소스를 지금 한 번 가져오고, `summarize`는 요약을 기다리는 항목을 요약하고, `stats`는 하루치 로그를 집계한다."""
    setup_logging()
    args = sys.argv[1:]
    if args == ["poll"]:
        print(f"새 글 {poll_all()}건")
    elif args[:1] == ["stats"] and len(args) <= 2:
        stats(args[1] if len(args) == 2 else datetime.now(KST).strftime("%Y-%m-%d"))
    elif args[:1] == ["summarize"] and len(args) <= 2 and (len(args) == 1 or args[1].isdigit()):
        summarize(int(args[1]) if len(args) == 2 else 30)
    else:
        print(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main()