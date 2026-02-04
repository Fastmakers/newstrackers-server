from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "News Tracker"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "News Tracker Agent Service"

    # API
    ALLOWED_ORIGINS: list[str] = ["*"]

    # LLM
    OPENAI_API_KEY: str = ""


settings = Settings()
