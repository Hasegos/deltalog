# ──────────────────────────────────────
# 1. 모델 가격
# ──────────────────────────────────────
MODEL_DATA_PATH = "data/models.toml"
MODEL_ID_RE = r"[a-z0-9][a-z0-9.\-]*"
MODEL_RESERVED_IDS = ("cost",)    # /models/cost는 계산기 주소라 모델 ID로 쓸 수 없다
MODEL_STALE_DAYS = 90    # 확인한 지 이 일수가 지난 가격에는 다시 확인하라는 경고를 붙인다
MODEL_SIBLINGS = 6    # 상세 페이지 아래에 붙일 같은 제공사 다른 모델 수


# ──────────────────────────────────────
# 2. 비용 계산기
# ──────────────────────────────────────
COST_DEFAULTS = {"input_tokens": 1000, "output_tokens": 500, "requests": 10000}