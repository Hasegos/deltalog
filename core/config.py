from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env`와 환경변수에서 읽은 설정 값 묶음."""

    PROJECT_NAME: str = "Deltalog"
    DATABASE_URL: str
    GITHUB_TOKEN: str = ""
    POLL_INTERVAL_MIN: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()