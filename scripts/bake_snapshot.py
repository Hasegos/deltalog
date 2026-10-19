"""운영 사이트를 크롤링해서 Cloudflare Pages에 올릴 정적 스냅샷(dist)을 만든다.

사용법: python scripts/bake_snapshot.py [출력 폴더]
환경변수
- SNAPSHOT_BASE: 대상 주소 (기본 https://deltalog.kr)
- SNAPSHOT_WAIT: 원본이 응답하기를 기다리는 초 (기본 180)
- SKIP_IF_DOWN: 1이면 원본이 꺼져 있을 때 오류 없이 끝낸다. 출력 폴더는 만들지 않는다
- SNAPSHOT_URL: 지금 배포된 스냅샷 주소. 굽은 sitemap.xml과 홈이 같으면 출력 폴더를 지워 배포를 생략한다
원본이 아니라 Worker 폴백(X-Served-By 헤더)이 응답한 페이지는 실패로 보고, 하나라도 실패하면 종료 코드 1로 끝난다.
Cloudflare가 요청마다 끼워 넣는 봇 판별 스크립트(__CF$cv$params)는 굽는 값이 매번 달라져서 지운다.
"""
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = os.environ.get("SNAPSHOT_BASE", "https://deltalog.kr").rstrip("/")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
WAIT_SECONDS = int(os.environ.get("SNAPSHOT_WAIT", "180"))
SKIP_IF_DOWN = os.environ.get("SKIP_IF_DOWN") == "1"
SNAPSHOT_URL = os.environ.get("SNAPSHOT_URL", "").rstrip("/")
WORKERS = 6
MIN_PAGES = 100
UA = "deltalog-snapshot/1.0"
ASSET_RE = re.compile(r'''(?:href|src)=["'](/[^"'#]+?)["']''')
CSS_URL_RE = re.compile(r'url\(["\']?(/[^"\')]+)["\']?\)')
ASSET_EXT = (".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".txt")
CF_INJECT_RE = re.compile(r"(?s)<script>(?:(?!</script>).)*?__CF\$cv\$params(?:(?!</script>).)*?</script>")
EMAIL_RE = re.compile(rb"data-cfemail=\"[0-9a-f]+\"|email-protection#[0-9a-f]+")
ROBOTS_MANAGED_RE = re.compile(r"(?s)# As a condition of accessing.*?# END Cloudflare Managed Content\s*")

errors: list[str] = []


def fetch(path: str) -> tuple[int, bytes]:
    """원본이 응답한 결과만 돌려준다. 폴백 응답이나 네트워크 오류는 세 번 시도하고 실패로 기록한다."""
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, headers, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, exc.headers, exc.read()
        except Exception:
            time.sleep(1 + attempt)
            continue
        if headers.get("X-Served-By") or status >= 500:
            time.sleep(2 + attempt)
            continue
        return status, body
    errors.append(f"origin not serving: {path}")
    return 0, b""


def wait_for_origin() -> None:
    """원본이 응답하기를 기다린다. 끝내 응답하지 않으면 SKIP_IF_DOWN일 때 정상 종료하고, 아니면 실패로 끝낸다."""
    deadline = time.time() + WAIT_SECONDS
    while True:
        req = urllib.request.Request(BASE + "/", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200 and not resp.headers.get("X-Served-By"):
                    return
        except Exception:
            pass
        if time.time() >= deadline:
            break
        time.sleep(5)
    if SKIP_IF_DOWN:
        print("원본이 꺼져 있어 굽기를 건너뛴다")
        sys.exit(0)
    sys.exit("원본이 응답하지 않아 스냅샷을 만들지 않는다")


def page_file(path: str) -> Path:
    clean = urllib.parse.unquote(path).strip("/")
    return OUT / ("index.html" if not clean else clean + ".html")


def asset_file(path: str) -> Path:
    return OUT / urllib.parse.unquote(path).lstrip("/")


def bake_page(path: str) -> tuple[str, bytes]:
    status, body = fetch(path)
    if status == 0:
        return path, b""
    if status != 200:
        errors.append(f"{status} {path}")
        return path, b""
    body = CF_INJECT_RE.sub("", body.decode("utf-8")).encode("utf-8")
    page_file(path).parent.mkdir(parents=True, exist_ok=True)
    page_file(path).write_bytes(body)
    return path, body


def bake_asset(path: str) -> bytes:
    status, body = fetch(path)
    if status == 0:
        return b""
    if status != 200:
        errors.append(f"{status} asset {path}")
        return b""
    target = asset_file(path.split("?")[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return body


def comparable(body: bytes) -> bytes:
    """Cloudflare가 요청마다 다르게 바꾸는 이메일 난독화 값을 지워 비교할 수 있게 한다."""
    return EMAIL_RE.sub(b"", body)


def unchanged() -> bool:
    """굽은 sitemap.xml과 홈이 지금 배포된 스냅샷과 같은지 본다. 하나라도 읽지 못하면 다르다고 본다."""
    if not SNAPSHOT_URL:
        return False
    for name, path in (("sitemap.xml", "/sitemap.xml"), ("index.html", "/")):
        try:
            req = urllib.request.Request(SNAPSHOT_URL + path, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                deployed = resp.read()
        except Exception:
            return False
        if comparable(deployed) != comparable((OUT / name).read_bytes()):
            return False
    return True


def main() -> None:
    wait_for_origin()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    _, sitemap = fetch("/sitemap.xml")
    (OUT / "sitemap.xml").write_bytes(sitemap)
    paths = [urllib.parse.urlparse(u).path for u in re.findall(r"<loc>([^<]+)</loc>", sitemap.decode("utf-8"))]
    print(f"sitemap urls: {len(paths)}")

    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(bake_page, paths))
    saved = sum(1 for _, body in results if body)
    print(f"pages saved: {saved}")

    status, body = fetch("/__snapshot_404_probe__")
    if status == 404:
        (OUT / "404.html").write_bytes(body)
        results.append(("/404", body))
    else:
        errors.append(f"404 probe returned {status}")

    assets: set[str] = set()
    for _, body in results:
        for ref in ASSET_RE.findall(body.decode("utf-8", "ignore")):
            if not ref.startswith("/cdn-cgi/") and ref.split("?")[0].lower().endswith(ASSET_EXT):
                assets.add(ref)
    assets |= {"/robots.txt", "/favicon.ico"}

    with ThreadPoolExecutor(WORKERS) as pool:
        bodies = dict(zip(sorted(assets), pool.map(bake_asset, sorted(assets))))

    nested = {
        sub
        for ref, body in bodies.items()
        if ref.split("?")[0].lower().endswith(".css")
        for sub in CSS_URL_RE.findall(body.decode("utf-8", "ignore"))
        if sub not in assets
    }
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(bake_asset, sorted(nested)))
    print(f"assets saved: {len(assets) + len(nested)}")

    robots = OUT / "robots.txt"
    if robots.exists():
        robots.write_text(ROBOTS_MANAGED_RE.sub("", robots.read_text("utf-8")), "utf-8")

    files = [p for p in OUT.rglob("*") if p.is_file()]
    print(f"files: {len(files)}, size: {sum(p.stat().st_size for p in files) / 1e6:.1f} MB")
    print(f"errors: {len(errors)}")
    for e in errors[:20]:
        print("  ", e)
    if errors or saved < MIN_PAGES or len(paths) < MIN_PAGES:
        sys.exit("검증 실패: 스냅샷을 배포하지 않는다")
    if unchanged():
        shutil.rmtree(OUT)
        print("변경 없음: 배포를 건너뛴다")


main()