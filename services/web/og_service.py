import json
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from core.constants.og import (
    OG_ACCENT,
    OG_BG,
    OG_BODY_BOTTOM,
    OG_CACHE_SIZE,
    OG_CATEGORY_COLORS,
    OG_CHIP_COLUMN,
    OG_DIM,
    OG_FG,
    OG_FIRST_CATEGORIES,
    OG_FONT,
    OG_HEIGHT,
    OG_LINE,
    OG_MARGIN,
    OG_MUTED,
    OG_RELEASE_ROWS,
    OG_WIDTH,
)
from services.web.news_service import build_news_detail
from services.web.release_service import build_release
from services.web.weekly_service import build_weekly

FONT_PATH = Path(__file__).resolve().parents[2] / OG_FONT


@lru_cache(maxsize=32)
def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    """한글 글꼴(가변 글꼴)의 크기와 굵기별 글꼴 객체를 만든다."""
    font = ImageFont.truetype(str(FONT_PATH), size)
    font.set_variation_by_axes([weight])
    return font


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    """줄을 나눈다. 띄어쓰기에서 나누고, 한 단어가 한 줄보다 길 때만 글자 단위로 자른다. `max_lines`를 넘으면 마지막 줄 끝을 `…`로 줄인다."""
    lines: list[str] = []
    current = ""
    for char in " ".join(text.split()):
        if draw.textlength(current + char, font=font) <= width:
            current += char
            continue
        cut = current.rfind(" ")
        if char != " " and cut > 0:
            lines.append(current[:cut])
            current = current[cut + 1 :] + char
        else:
            lines.append(current.rstrip())
            current = char.lstrip()
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _draw_brand(draw: ImageDraw.ImageDraw) -> None:
    draw.text((OG_MARGIN, 44), "Δ deltalog", font=_font(30, 700), fill=OG_FG)
    tagline = "AI 코딩 도구 릴리스 노트 한국어 요약"
    font = _font(24, 400)
    draw.text((OG_WIDTH - OG_MARGIN - draw.textlength(tagline, font=font), 50), tagline, font=font, fill=OG_DIM)
    draw.text((OG_MARGIN, OG_HEIGHT - 58), "deltalog.kr", font=_font(26, 500), fill=OG_ACCENT)
    note = "AI가 요약했습니다. 원문을 확인하세요"
    font = _font(24, 400)
    draw.text((OG_WIDTH - OG_MARGIN - draw.textlength(note, font=font), OG_HEIGHT - 56), note, font=font, fill=OG_DIM)


@lru_cache(maxsize=OG_CACHE_SIZE)
def _render(card_json: str) -> bytes:
    """카드 값(JSON)으로 1200x630 PNG를 그린다. 같은 값이면 다시 그리지 않는다."""
    card = json.loads(card_json)
    image = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), OG_BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 14, OG_HEIGHT), fill=OG_ACCENT)
    draw.line((OG_MARGIN, 108, OG_WIDTH - OG_MARGIN, 108), fill=OG_LINE, width=2)
    _draw_brand(draw)
    inner = OG_WIDTH - OG_MARGIN * 2

    y = 128
    draw.text((OG_MARGIN, y), card["kicker"], font=_font(36, 700), fill=OG_ACCENT)
    y += 54
    title_font = _font(card["title_size"], 700)
    for line in _wrap(draw, card["title"], title_font, inner, card["title_lines"]):
        draw.text((OG_MARGIN, y), line, font=title_font, fill=OG_FG)
        y += int(card["title_size"] * 1.28)
    if card["meta"]:
        draw.text((OG_MARGIN, y + 10), card["meta"], font=_font(26, 400), fill=OG_DIM)
        y += 52
    y += 22

    body_font = _font(28, 400)
    label_font = _font(21, 700)
    text_x = OG_MARGIN + OG_CHIP_COLUMN
    for row in card["rows"]:
        lines = _wrap(draw, row["text"], body_font, OG_WIDTH - OG_MARGIN - text_x, 2)
        height = len(lines) * 38 + 18
        if y + height > OG_BODY_BOTTOM:
            break
        chip_w = int(draw.textlength(row["label"], font=label_font)) + 24
        draw.rounded_rectangle((OG_MARGIN, y + 3, OG_MARGIN + chip_w, y + 37), radius=8, fill=OG_CATEGORY_COLORS[row["key"]])
        draw.text((OG_MARGIN + 12, y + 7), row["label"], font=label_font, fill="#ffffff")
        for n, line in enumerate(lines):
            draw.text((text_x, y + n * 38), line, font=body_font, fill=OG_FG)
        y += height
    if card["text"]:
        text_font = _font(30, 400)
        for line in _wrap(draw, card["text"], text_font, inner, min(card["text_lines"], max(1, (OG_BODY_BOTTOM - y) // 44))):
            draw.text((OG_MARGIN, y), line, font=text_font, fill=OG_MUTED)
            y += 44

    buffer = BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def _card(kicker: str, title: str, meta: str = "", rows: list[dict] | None = None, text: str = "", title_size: int = 64, title_lines: int = 2, text_lines: int = 3) -> dict:
    return {"kicker": kicker, "title": title, "meta": meta, "rows": rows or [], "text": text, "title_size": title_size, "title_lines": title_lines, "text_lines": text_lines}


def render(card: dict) -> bytes:
    """카드 값으로 OG 이미지(PNG)를 돌려준다."""
    return _render(json.dumps(card, ensure_ascii=False, sort_keys=True))


def release_card(db: Session, slug: str, key: str) -> dict | None:
    """릴리스 상세의 OG 카드 값을 만든다. 도구 이름, 버전, 요약 `OG_RELEASE_ROWS`개를 담는다. breaking · 보안이 먼저, 나머지는 중요도 순이다. 그런 릴리스가 없으면 `None`."""
    values = build_release(db, slug, key, "")
    if values is None:
        return None
    ranked = [
        (group["key"] not in OG_FIRST_CATEGORIES, -row["importance"], order, group, row)
        for order, group in enumerate(values["groups"])
        for row in group["rows"]
        if row["summary"]
    ]
    rows = [{"key": group["key"], "label": group["label"], "text": row["summary"]} for _, _, _, group, row in sorted(ranked, key=lambda r: r[:3])[:OG_RELEASE_ROWS]]
    meta = f"{values['date']} 릴리스 · 변경 항목 {values['total']}개"
    return _card(values["name"], values["version"], meta, rows, title_size=72, title_lines=1)


def news_card(db: Session, news_id: int) -> dict | None:
    """소식 상세의 OG 카드 값을 만든다. 회사, 한국어 제목, 요약을 담는다. 그런 소식이 없으면 `None`."""
    values = build_news_detail(db, news_id, "")
    if values is None:
        return None
    return _card(f"{values['company']} 공식 소식", values["title"], f"{values['day']}", text=values["summary"], title_size=54, title_lines=3, text_lines=3)


def weekly_card(db: Session, monday) -> dict | None:
    """주간 요약의 OG 카드 값을 만든다. 제목과 기간, 개요를 담는다. 그 주의 요약이 없으면 `None`."""
    values = build_weekly(db, monday)
    if not values or not values.get("digest"):
        return None
    digest = values["digest"]
    return _card("주간 요약", digest.headline, values["range"], text=digest.overview, title_size=54, title_lines=2, text_lines=4)