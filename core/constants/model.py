# ──────────────────────────────────────
# 1. 모델 가격
# ──────────────────────────────────────
MODEL_DATA_PATH = "data/models.toml"
MODEL_ID_RE = r"[a-z0-9][a-z0-9.\-]*"
MODEL_RESERVED_IDS = ("cost",)
MODEL_STALE_DAYS = 90
MODEL_SIBLINGS = 6
EDITORIAL_KEYS = ("use_when", "avoid_when", "migration", "notes")

# 가격 자동 대조에 쓰는 공식 가격표 원문(마크다운) 주소와, 모델을 찾는 열쇠(Anthropic은 이름, 나머지는 ID), 표준 가격표 뒤(배치 · 캐시 등 다른 표)를 자르는 머리글 패턴
PRICE_DOCS = {
    "Anthropic": {"url": "https://platform.claude.com/docs/en/about-claude/pricing.md", "key": "name", "stop": r"(?m)^## (?!Model pricing)"},
    "OpenAI": {"url": "https://developers.openai.com/api/docs/pricing.md", "key": "id", "stop": r"(?m)^### (?!Standard)"},
    "Google": {"url": "https://ai.google.dev/gemini-api/docs/pricing.md.txt", "key": "id"},
}
# 한 제공사에서 이 비율을 넘게 못 찾으면 모델별 오류 대신 "가격표 형식이 바뀐 듯함" 하나로 알린다
PRICE_FORMAT_MISS_RATIO = 0.5
PRICE_SNIPPET_CHARS = 160


# ──────────────────────────────────────
# 2. 비용 계산기
# ──────────────────────────────────────
COST_DEFAULTS = {"input_tokens": 1000, "output_tokens": 500, "requests": 10000}