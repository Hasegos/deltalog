from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

CATEGORIES = {
    "feature": ("+", "신기능"),
    "bugfix": ("~", "수정"),
    "breaking": ("!", "breaking"),
    "security": ("◆", "보안"),
    "other": ("·", "기타"),
}

TOPICS = ["에이전트", "MCP·플러그인", "훅", "보안·권한", "성능", "UI"]

PAGE_SIZE = 20
SPARK_WEEKS = 8
IMPORTANT_MIN = 4