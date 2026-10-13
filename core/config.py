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
    GITHUB_TOKEN: str = ""
    POLL_INTERVAL_MIN: int = 30

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