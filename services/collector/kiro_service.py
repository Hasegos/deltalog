import json
import re

PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ROW = re.compile(r"^([0-9a-f]+):(.*)$")
MDX_COMMENT = re.compile(r"\{/.*?/\}")
CHANGELOG_CLASS = "changelog prose-prey"


def _rows(html: str) -> dict[str, object]:
    """Next.js 페이지의 `self.__next_f.push` 조각을 이어 붙여 `행 ID -> JSON` 표로 만든다. JSON이 아닌 행은 버린다."""
    stream = "".join(json.loads(chunk) for chunk in PUSH.findall(html))
    rows: dict[str, object] = {}
    for line in stream.split("\n"):
        match = ROW.match(line)
        if match and match.group(2)[:1] in ('[', '{', '"'):
            try:
                rows[match.group(1)] = json.loads(match.group(2))
            except ValueError:
                continue
    return rows


def _is_element(node: object) -> bool:
    return isinstance(node, list) and len(node) >= 4 and node[0] == "$" and isinstance(node[3], dict)


def _text(node: object, rows: dict[str, object]) -> str:
    """React 요소 트리에서 글자만 모은다. `code`는 역따옴표로 감싼다. `$L12` 같은 참조는 그 행을 찾아 따라간다."""
    if isinstance(node, str):
        if node.startswith("$L") and node[2:] in rows:
            return _text(rows[node[2:]], rows)
        return "" if node.startswith("$") else node
    if _is_element(node):
        inner = _text(node[3].get("children"), rows)
        return f"`{inner}`" if node[1] == "code" else inner
    if isinstance(node, list):
        return "".join(_text(child, rows) for child in node)
    return ""


def _walk(node: object, rows: dict[str, object], out: list[str]) -> None:
    """변경 로그 본문 트리를 걸으며 `## 제목`, `P 문단`, `- 목록` 줄을 순서대로 모은다. 접는 상자(`title` 속성)는 제목으로 바꾼다."""
    if isinstance(node, str):
        if node.startswith("$L") and node[2:] in rows:
            _walk(rows[node[2:]], rows, out)
        return
    if _is_element(node):
        tag, props = node[1], node[3]
        children = props.get("children")
        if tag in ("h2", "h3"):
            out.append("## " + _text(children, rows).strip())
        elif tag == "p":
            out.append("P " + _text(children, rows).strip())
        elif tag == "li":
            out.append("- " + _text(children, rows).strip())
        else:
            if isinstance(props.get("title"), str) and not props["title"].startswith("$"):
                out.append("## " + props["title"])
            _walk(children, rows, out)
        return
    if isinstance(node, list):
        for child in node:
            _walk(child, rows, out)


def _find_body(node: object) -> list | None:
    """트리에서 변경 로그 본문 `div`(`changelog prose-prey` 클래스)를 찾는다."""
    if _is_element(node) and CHANGELOG_CLASS in str(node[3].get("className", "")):
        return node
    children = node[3].values() if _is_element(node) else node.values() if isinstance(node, dict) else node if isinstance(node, list) else []
    for child in children:
        found = _find_body(child)
        if found:
            return found
    return None


def page_body(html: str) -> str:
    """Kiro 변경 로그 글 페이지(`kiro.dev/changelog/<종류>/<글>`)에서 본문을 `split_items`가 나눌 수 있는 Markdown으로 바꾼다.

    개선 · 수정 목록은 접는 상자라 HTML에는 비어 있고 Next.js가 심은 데이터에만 있어서, 그 데이터를 읽는다.
    목록이 있는 글은 문단도 `-` 항목으로 두고(앞 `##` 제목이 힌트가 된다), 목록이 없는 글(모델 소식)은 문단을 그대로 둔다.

    Args:
        html: 글 페이지 HTML
    Returns:
        Markdown. 본문을 못 찾으면 빈 문자열
    """
    rows = _rows(html)
    for value in rows.values():
        body = _find_body(value)
        if body is None:
            continue
        out: list[str] = []
        _walk(body[3].get("children"), rows, out)
        lines = [MDX_COMMENT.sub("", line).strip() for line in out]
        lines = [line for line in lines if line not in ("", "-", "P", "##")]
        has_list = any(line.startswith("- ") for line in lines)
        return "\n".join(f"- {line[2:]}" if has_list and line.startswith("P ") else line[2:] if line.startswith("P ") else line for line in lines)
    return ""