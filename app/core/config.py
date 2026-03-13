from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Project info
    PROJECT_NAME: str = "NewsTrackers AI"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "AI-Powered Job Interview and Career Development Platform"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # LLM
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"
    LLM_MAX_TOKENS: int = 2000
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT: int = 60

    # Database
    DATABASE_URL: str = ""

    # JWT (security.py 에서 사용)
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 30

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    # Application
    DEBUG: bool = False
    RUN_WORKER_IN_API: bool = True
    WORKER_POLL_INTERVAL_SEC: float = 3.0
    WORKER_MAX_CONCURRENT: int = 3

    # Project paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    FONTS_DIR: Path = DATA_DIR / "fonts"

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.FONTS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
