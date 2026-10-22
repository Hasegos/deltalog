# ──────────────────────────────────────
# 1. 모델 가격
# ──────────────────────────────────────
MODEL_DATA_PATH = "data/models.toml"
MODEL_ID_RE = r"[a-z0-9][a-z0-9.\-]*"
MODEL_RESERVED_IDS = ("cost",)
MODEL_STALE_DAYS = 90
MODEL_SIBLINGS = 6


# ──────────────────────────────────────
# 2. 비용 계산기
# ──────────────────────────────────────
COST_DEFAULTS = {"input_tokens": 1000, "output_tokens": 500, "requests": 10000}