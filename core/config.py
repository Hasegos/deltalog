import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """`.env`와 환경변수에서 읽은 설정 값 묶음."""

    PROJECT_NAME: str = "Deltalog"
    POSTGRESQL_USERNAME: str
    POSTGRESQL_PASSWORD: str
    POSTGRESQL_SERVER: str = "db"
    POSTGRESQL_PORT: int = 5432
    POSTGRESQL_DATABASE: str
    POOL_SIZE: int = 5
    MAX_OVERFLOW: int = 10
    POOL_RECYCLE: int = 3600
    POOL_TIMEOUT: int = 30
    POOL_PRE_PING: bool = True
    AUTO_CREATE_TABLES: bool = True
    GITHUB_TOKEN: str = ""
    POLL_INTERVAL_MIN: int = 30
    NEWS_POLL_INTERVAL_MIN: int = 60
    GITHUB_API_URL: str = "https://api.github.com/repos/{repo}/releases"
    GITHUB_PER_PAGE: int = 30
    GITHUB_TIMEOUT_SEC: int = 20
    FEED_TIMEOUT_SEC: int = 20
    FEED_MAX_ENTRIES: int = 15
    FEED_MAX_ITEM_CHARS: int = 900
    FEED_PAGE_DELAY_SEC: float = 0.5
    JETBRAINS_TIMEOUT_SEC: int = 30
    JETBRAINS_MAX_RELEASES: int = 15
    COLLECTOR_USER_AGENT: str = "deltalog/0.1 (+https://github.com/Hasegos/deltalog)"
    LLM_TEMPERATURE: float = 0.1
    LLM_TOP_P: float = 0.9
    LLM_MAX_RETRIES: int = 2
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_DAILY_LIMIT: int
    GEMINI_RPM: int
    GEMINI_BATCH_SIZE: int = 25
    GEMINI_MAX_TOKENS: int = 8192
    GEMINI_TIMEOUT: int = 180
    GEMINI_REASONING_EFFORT: str = ""
    GEMINI_COOLDOWN_MIN: int = 10
    FAILED_MAX_ATTEMPTS: int = 3
    AUTO_SUMMARIZE: bool = True
    SUMMARIZE_INTERVAL_MIN: int = 3
    SUMMARIZE_BATCH_LIMIT: int = 200
    LOG_DIR: str = "logs"
    LOG_RETENTION_DAYS: int = 30
    TRUST_PROXY: bool = False
    SITE_URL: str = ""
    API_KEY: str = ""
    ADSENSE_CLIENT: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("PROJECT_NAME", mode="before")
    @classmethod
    def default_project_name(cls, value: str) -> str:
        """`PROJECT_NAME=`처럼 비어 있으면 기본 이름을 쓴다.

        Args:
            value: `.env`에서 읽은 값
        Returns:
            비어 있지 않은 이름
        """
        return value or "Deltalog"

    @property
    def adsense_client(self) -> str:
        """`ADSENSE_CLIENT`가 `ca-pub-숫자` 모양일 때만 그 값을, 아니면 빈 값을 돌려준다. 빈 값이면 광고 코드를 넣지 않는다."""
        value = self.ADSENSE_CLIENT.strip()
        return value if re.fullmatch(r"ca-pub-\d+", value) else ""

    @property
    def DATABASE_URL(self) -> URL:
        """`POSTGRESQL_*` 값으로 SQLAlchemy 접속 주소를 만든다. 비밀번호의 특수문자는 알아서 처리된다."""
        return URL.create(
            "postgresql+psycopg",
            username=self.POSTGRESQL_USERNAME,
            password=self.POSTGRESQL_PASSWORD,
            host=self.POSTGRESQL_SERVER,
            port=self.POSTGRESQL_PORT,
            database=self.POSTGRESQL_DATABASE,
        )


settings = Settings()