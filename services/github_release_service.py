import re
from dataclasses import dataclass
from datetime import datetime

import httpx

API_URL = "https://api.github.com/repos/{repo}/releases"
PER_PAGE = 30
TIMEOUT_SEC = 20


@dataclass
class Release:
    """GitHub 릴리스 하나를 `entry`에 넣을 모양으로 바꾼 값."""

    external_id: str
    version: str
    title: str
    published_at: datetime
    url: str
    body: str
    prerelease: bool


@dataclass
class FetchResult:
    """릴리스 목록 요청 결과. `releases`가 `None`이면 변경이 없다는 뜻이다(304)."""

    etag: str | None
    releases: list[Release] | None


def version_of(tag: str) -> str:
    """태그에서 앞의 접두어를 떼어 버전만 남긴다.

    Args:
        tag: `v2.1.296`, `rust-v0.162.1` 같은 태그
    Returns:
        `2.1.296`, `0.162.1` 같은 버전. 숫자가 없으면 태그 그대로
    """
    return re.sub(r"^\D*", "", tag) or tag


def fetch_releases(repo: str, etag: str | None, token: str = "") -> FetchResult:
    """GitHub에서 최근 릴리스를 받는다. 저장해 둔 ETag를 보내 변경이 없으면 304로 끝낸다.

    Args:
        repo: `owner/name`
        etag: 지난번 응답의 ETag. 없으면 처음 받는다
        token: GitHub 토큰. 비워도 되지만 호출 한도가 낮다
    Returns:
        새 ETag와 릴리스 목록. 304면 목록이 `None`
    Raises:
        httpx.HTTPError: 네트워크 오류나 304, 200 외의 응답
    """
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if etag:
        headers["If-None-Match"] = etag
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.get(
        API_URL.format(repo=repo), params={"per_page": PER_PAGE}, headers=headers, timeout=TIMEOUT_SEC
    )
    if response.status_code == 304:
        return FetchResult(etag=etag, releases=None)
    response.raise_for_status()

    releases = [
        Release(
            external_id=raw["tag_name"],
            version=version_of(raw["tag_name"]),
            title=raw.get("name") or raw["tag_name"],
            published_at=datetime.fromisoformat(raw["published_at"]),
            url=raw["html_url"],
            body=raw.get("body") or "",
            prerelease=bool(raw.get("prerelease")),
        )
        for raw in response.json()
        if not raw.get("draft") and raw.get("published_at")
    ]
    return FetchResult(etag=response.headers.get("ETag"), releases=releases)