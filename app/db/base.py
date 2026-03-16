from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# 1. 환경 변수 검증: URL이 없으면 즉시 에러 발생 (Fail-Fast)
if not settings.DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment variables.")

# 2. Engine 생성: None 케이스를 제거하여 안정성 확보
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
) 

# 3. SessionLocal: 항상 유효한 engine에 바인딩됨
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
