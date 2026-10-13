import re

BULLET = re.compile(r"^[-*]\s+(.*)$")
HEADING = re.compile(r"^#{2,6}\s+(.*)$")


def split_items(body: str, title: str) -> list[str]:
    """릴리스 본문(Markdown)을 요약 단위로 나눈다.

    최상위 `-` 줄 하나가 항목 하나이고, 들여쓴 줄은 앞 항목에 붙는다. 바로 위의 `##` 제목은
    요약에 쓸 힌트로 항목 앞에 붙인다. 항목이 하나도 없으면 본문 전체를, 본문도 없으면 제목을 한 항목으로 둔다.

    Args:
        body: 릴리스 본문
        title: 릴리스 제목. 본문이 비었을 때 쓴다
    Returns:
        항목 원문 목록. 비어 있지 않다
    """
    items: list[str] = []
    heading = ""
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            text = " ".join(part for part in current if part).strip()
            items.append(f"[{heading}] {text}" if heading else text)
        current = None

    for line in body.splitlines():
        stripped = line.strip()
        match = BULLET.match(line)
        if match:
            flush()
            current = [match.group(1).strip()]
        elif HEADING.match(stripped):
            flush()
            heading = HEADING.match(stripped).group(1).strip()
        elif current is not None and line[:1] in (" ", "\t") and stripped:
            current.append(stripped)
        elif not stripped:
            continue
        else:
            flush()
    flush()

    if items:
        return items
    return [body.strip() or title]