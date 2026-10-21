# ──────────────────────────────────────
# 1. OG 이미지 (페이지별 공유 카드)
# ──────────────────────────────────────
OG_WIDTH = 1200
OG_HEIGHT = 630
OG_MARGIN = 64
OG_FONT = "static/fonts/NotoSansKR.ttf"    # 가변 글꼴(굵기 축 하나). OFL 라이선스는 같은 폴더의 OFL.txt
OG_CACHE_SIZE = 256                        # 같은 내용의 카드를 다시 그리지 않도록 메모리에 둘 PNG 수
OG_CACHE_SEC = 3600                        # 브라우저와 Cloudflare가 이미지를 재사용하는 시간(초)
OG_BODY_BOTTOM = 556                       # 본문(요약 줄)이 내려갈 수 있는 맨 아래 y. 그 밑은 푸터 자리
OG_CHIP_COLUMN = 136                       # 유형 칩 줄의 너비. 요약 글자의 왼쪽을 맞춘다
OG_RELEASE_ROWS = 3                        # 릴리스 카드에 보여줄 가장 중요한 요약 수

# 사이트 CSS의 밝은 테마 색(common.css)과 같다
OG_BG = "#f7f5f0"
OG_FG = "#1c1b18"
OG_MUTED = "#55514a"
OG_DIM = "#6f6a60"
OG_LINE = "#e3ded2"
OG_ACCENT = "#3451d1"
OG_CATEGORY_COLORS = {
    "feature": "#167a48",
    "bugfix": "#566273",
    "breaking": "#c3352b",
    "security": "#946008",
    "other": "#6f6a60",
}