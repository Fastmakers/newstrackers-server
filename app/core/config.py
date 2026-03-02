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

    # Claude API
    ANTHROPIC_API_KEY: str = ""

    # OpenAI API (쿼리 임베딩 생성용 — text-embedding-3-small)
    OPENAI_API_KEY: str = ""
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"

    # PostgreSQL (pgvector)
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/newstracker"

    # 산업군별 검색 키워드
    INDUSTRY_KEYWORDS: list[str] = [
        "반도체",
        "AI 인공지능",
        "금융",
        "제조업",
        "바이오 헬스케어",
        "유통 커머스",
        "콘텐츠 미디어",
        "에너지 환경",
        "자동차 모빌리티",
        "건설 부동산",
        "방산",
    ]


settings = Settings()
