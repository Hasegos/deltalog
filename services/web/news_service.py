from datetime import datetime, timedelta
from math import ceil
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from core.constants.news import COMPANY_TOOLS, HEADLINE_DAYS, NEWS_COMPANIES, NEWS_PAGE_SIZE, NEWS_TABS, NEWS_TYPES, RELATED_DAYS, RELATED_LIMIT
from core.constants.page import KST
from core.constants.taxonomy import TOPICS
from crud import entry_crud, news_crud
from models.news_model import News
from services.web.home_service import _ago, _day_label
from services.web.release_service import release_path


def _url(params: dict[str, str], **override: str | None) -> str:
    """현재 필터에 조건 하나를 바꾼 주소를 만든다. 이미 같은 값이면 그 조건을 뺀다.

    Args:
        params: 현재 필터
        override: 바꿀 조건. 값이 `None`이면 그 조건을 뺀다
    Returns:
        `/news` 또는 `/news?...` 주소
    """
    merged = dict(params)
    for key, value in override.items():
        if value is None or merged.get(key) == value:
            merged.pop(key, None)
        else:
            merged[key] = value
    return "/news?" + urlencode(merged) if merged else "/news"


def _row(article: News, now: datetime) -> dict:
    """글 하나를 화면에 쓸 값으로 바꾼다.

    Args:
        article: 요약이 끝난 글
        now: 기준 시각
    Returns:
        템플릿에 넘길 값
    """
    return {
        "company": article.company,
        "title": article.title_ko or article.title,
        "summary": article.summary_ko or "",
        "topic": article.topic,
        "importance": article.importance or 0,
        "type_label": NEWS_TYPES.get(article.news_type or "", ""),
        "ago": _ago(article.published_at, now),
        "day": article.published_at.astimezone(KST).strftime("%Y-%m-%d"),
        "day_label": _day_label(article.published_at, now),
        "url": article.url if article.url.startswith(("https://", "http://")) else "#",
    }


def _related(db: Session, articles: list[News]) -> dict[int, list[dict]]:
    """소식마다 같은 제작사의 릴리스 중 게시일이 앞뒤 `RELATED_DAYS`일 이내인 것을 가까운 순으로 `RELATED_LIMIT`개 찾는다. 질의는 한 번만 한다.

    Args:
        db: DB 세션
        articles: 화면에 보일 소식
    Returns:
        소식 ID별 `{"label", "path"}` 목록. 짝이 없는 소식은 들어 있지 않다
    """
    if not articles:
        return {}
    span = timedelta(days=RELATED_DAYS)
    slugs = sorted({slug for a in articles for slug in COMPANY_TOOLS.get(a.company, [])})
    found = entry_crud.list_between(db, slugs, min(a.published_at for a in articles) - span, max(a.published_at for a in articles) + span)
    result: dict[int, list[dict]] = {}
    for article in articles:
        mine = set(COMPANY_TOOLS.get(article.company, []))
        near = sorted(
            (pair for pair in found if pair[1].slug in mine and abs(pair[0].published_at - article.published_at) <= span),
            key=lambda pair: abs(pair[0].published_at - article.published_at),
        )[:RELATED_LIMIT]
        if near:
            result[article.id] = [{"label": f"{source.name} {entry.version or entry.title}", "path": release_path(source.slug, entry)} for entry, source in near]
    return result


def build_news(db: Session, company: str, tab: str, topic: str, q: str = "", page: int = 1, now: datetime | None = None) -> dict:
    """소식 화면에 필요한 값을 모두 만든다.

    Args:
        db: DB 세션
        company: 제작사 필터
        tab: `NEWS_TABS`의 키 (`all`, `imp`, `model`, `pricing`, `security`)
        topic: 주제 필터
        q: 검색어. 제목, 요약, 주제, 제작사에서 부분 일치를 찾는다
        page: 쪽 번호. 전체 쪽 수를 넘으면 마지막 쪽으로 본다
        now: 기준 시각. 비우면 현재 시각
    Returns:
        템플릿에 넘길 값
    """
    now = now or datetime.now(KST)
    company = company if company in NEWS_COMPANIES else ""
    tab = tab if tab in dict(NEWS_TABS) else "all"
    topic = topic if topic in TOPICS else ""
    q = q.strip()
    params = {key: value for key, value in (("company", company), ("tab", tab if tab != "all" else ""), ("topic", topic), ("q", q)) if value}

    by_company = news_crud.count_by_company(db)
    companies = [
        {"name": name, "count": by_company.get(name, 0), "active": name == company, "href": _url(params, company=name)}
        for name in NEWS_COMPANIES
    ]
    no_tab = {k: v for k, v in params.items() if k != "tab"}
    tabs = [
        {
            "label": label,
            "count": news_crud.count_news(db, company, key, topic, q),
            "active": key == tab,
            "href": _url(no_tab, tab=None if key == "all" else key),
        }
        for key, label in NEWS_TABS
    ]
    matched = next(t["count"] for t in tabs if t["active"])
    pages = max(1, ceil(matched / NEWS_PAGE_SIZE))
    page = min(page, pages)
    more = _url(params, page=str(page + 1)) if page < pages else None

    articles = news_crud.list_news(db, company, tab, topic, NEWS_PAGE_SIZE, (page - 1) * NEWS_PAGE_SIZE, q)
    rows = []
    last_day = ""
    related = _related(db, articles)
    for article in articles:
        row = _row(article, now)
        row["related"] = related.get(article.id, [])
        row["show_day"] = row["day"] != last_day
        last_day = row["day"]
        rows.append(row)

    top = None
    if not params and page == 1:
        found = news_crud.headline(db, now - timedelta(days=HEADLINE_DAYS))
        top = _row(found, now) if found else None

    return {
        "headline": top,
        "companies": companies,
        "total": sum(by_company.values()),
        "all_href": _url(params, company=None),
        "tabs": tabs,
        "topics": [{"name": t, "active": t == topic} for t in TOPICS],
        "hidden": {k: v for k, v in params.items() if k != "topic"},
        "search_hidden": {k: v for k, v in params.items() if k != "q"},
        "q": q,
        "rows": rows,
        "more": more,
        "filtered": bool(params),
    }