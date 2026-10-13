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
    LM_STUDIO_BASE_URL: str = ""
    LM_STUDIO_MODEL: str = ""
    LM_STUDIO_API_KEY: str = ""
    LM_STUDIO_TIMEOUT: int = 180
    LLM_TEMPERATURE: float = 0.1
    LLM_TOP_P: float = 0.9
    LLM_TOP_K: int = 40
    LLM_REPEAT_PENALTY: float = 1.0
    LLM_MAX_TOKENS: int = 4096
    LLM_MAX_RETRIES: int = 2
    AUTO_SUMMARIZE: bool = True
    SUMMARIZE_INTERVAL_MIN: int = 3
    SUMMARIZE_BATCH_LIMIT: int = 200
    LOG_DIR: str = "logs"
    LOG_RETENTION_DAYS: int = 30
    TRUST_PROXY: bool = False

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