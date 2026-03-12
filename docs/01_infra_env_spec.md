# 01_infra_env_spec.md — 인프라 및 환경 변수 명세

> **이 문서는 모든 환경 변수, DB 설정, 인덱스 설정의 단일 진실 공급원(Single Source of Truth)입니다.**
> AI 에이전트는 환경 설정 관련 코드 작성 시 반드시 이 명세서를 참조하십시오.

---

## 1. Configuration 원칙

- **12-Factor App 준수**: 모든 설정은 코드가 아닌 환경 변수로 주입한다.
- **Fail-Fast**: 필수 환경 변수 누락 시 서버 기동 단계(`app/core/config.py` import 시점)에서 즉시 `ValidationError`로 종료된다.
- **절대경로 .env 로딩**: `app/core/config.py`는 어느 디렉토리에서 실행해도 프로젝트 루트의 `.env`를 자동 탐색한다.

---

## 2. 표준 환경 변수 정의

### 2-1. Database (PostgreSQL)

| 변수명 | 필수 | 기본값 | 예시 |
|--------|------|--------|------|
| `DATABASE_URL` | **필수** | 없음 | `postgresql://user:pass@host:5432/dbname` |

```python
# ✅ 올바른 사용
DATABASE_URL = settings.DATABASE_URL

# ❌ 금지 — 호스트/자격증명 하드코딩
engine = create_engine("postgresql://admin:secret@prod.rds.amazonaws.com/news")
```

**Fail-Fast 구현:**
```python
class Settings(BaseSettings):
    DATABASE_URL: PostgresDsn  # None이면 ValidationError → 서버 기동 실패
```

### 2-2. LLM APIs

| 변수명 | 필수 | 사용처 |
|--------|------|--------|
| `OPENAI_API_KEY` | **필수** | 임베딩 (`text-embedding-3-small`) |
| `ANTHROPIC_API_KEY` | **필수** | Claude 분석 (`claude-sonnet-4-6`) |

```python
# ✅ 올바른 사용 — config.py에서만 접근
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# ❌ 금지 — 코드 내 직접 작성
client = anthropic.Anthropic(api_key="sk-ant-...")
```

### 2-3. Feature Flags

| 변수명 | 타입 | 기본값 | 설명 |
|--------|------|--------|------|
| `ENABLE_RERANKER` | `bool` | `False` | Cross-Encoder 리랭킹 활성화. `True`면 `BAAI/bge-reranker-v2-m3` 모델을 로드한다 (~1.1GB). 메모리 주의. |
| `DEBUG` | `bool` | `False` | FastAPI 디버그 모드 |

### 2-4. 전체 환경 변수 목록

```ini
# .env (프로젝트 루트)

# === 필수 (누락 시 기동 실패) ===
DATABASE_URL=postgresql://user:pass@host:5432/dbname
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# === 선택 ===
ENABLE_RERANKER=false
DEBUG=false
```

---

## 3. Pydantic Settings 구현 규칙

`app/core/config.py`는 아래 규칙을 모두 만족해야 한다.

### 3-1. 필수 필드 타입 검증
```python
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 필수 — 기본값 없음, None이면 Pydantic ValidationError
    DATABASE_URL: PostgresDsn
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: str

    # 선택 — 기본값 있음
    ENABLE_RERANKER: bool = False
    DEBUG: bool = False
```

### 3-2. 절대경로 .env 자동 탐색
```python
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent.parent / ".env",
        env_file_encoding="utf-8",
    )
```

> 이 방식으로 `scripts/`, `tests/`, 프로젝트 루트 어디서 실행해도 `.env`를 찾는다.

### 3-3. 싱글턴 인스턴스
```python
settings = Settings()  # 모듈 로드 시 1회만 생성 — 이후 import로 재사용
```

---

## 4. 데이터베이스 설정

### 4-1. 필수 PostgreSQL 확장

아래 확장은 서버 최초 기동 전 DB에 반드시 설치되어 있어야 한다.

| 확장 | 용도 | 설치 SQL |
|------|------|----------|
| `pgvector` | 벡터 유사도 검색 | `CREATE EXTENSION IF NOT EXISTS vector;` |
| `pg_trgm` | 한국어 트라이그램 키워드 검색 | `CREATE EXTENSION IF NOT EXISTS pg_trgm;` |

### 4-2. 필수 인덱스

아래 인덱스가 없으면 `search_chunks_by_keyword()` 가 전체 테이블 스캔(Seq Scan)으로 실행되어 수 초의 지연이 발생한다.

```sql
-- pg_trgm GIN 인덱스 (키워드 검색 성능)
CREATE INDEX IF NOT EXISTS idx_chunks_trgm
    ON news_chunks USING gin(chunk_text gin_trgm_ops);

-- pgvector HNSW 인덱스 (벡터 검색 성능)
-- 이미 생성되어 있어야 함. 없으면 아래 실행:
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON news_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**Alembic으로 마이그레이션 관리하는 방법:**
```bash
# 새 마이그레이션 파일 생성
alembic revision --autogenerate -m "add_pg_trgm_gin_index"

# 생성된 파일(alembic/versions/xxx.py)에서 upgrade() 함수 확인 후
alembic upgrade head  # DB에 인덱스 반영
```

### 4-3. SQLAlchemy Session 설정

```python
# app/db/base.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,     # 끊긴 연결 자동 재시도
    pool_size=10,           # 기본 커넥션 풀 크기
    max_overflow=20,        # 피크 시 최대 추가 커넥션
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

---

## 5. 배포 환경별 설정

| 환경 | DATABASE_URL 호스트 | ENABLE_RERANKER | DEBUG |
|------|---------------------|-----------------|-------|
| 로컬 개발 | `localhost:5432` | `false` | `true` |
| 스테이징 | AWS RDS 스테이징 엔드포인트 | `false` | `false` |
| 프로덕션 | AWS RDS 프로덕션 엔드포인트 | 서버 스펙에 따라 결정 | `false` |

> 각 환경마다 `.env.local`, `.env.staging`, `.env.prod` 파일을 별도 관리한다.
> `.env*` 파일은 `.gitignore`에 반드시 포함되어야 한다.

---

## 6. 환경 변수 검증 체크리스트 (AI Agent용)

새 코드를 작성하거나 리뷰할 때 아래 항목을 확인한다.

- [ ] 코드에 API 키, 비밀번호, 호스트 주소가 직접 문자열로 쓰여 있지 않은가?
- [ ] 새 환경 변수를 추가했다면 `app/core/config.py`의 `Settings` 클래스에 추가했는가?
- [ ] 필수 환경 변수에 `default` 값을 부여하지 않았는가? (필수는 기본값 없음)
- [ ] `.env.example` 파일에 새 변수의 키와 설명을 추가했는가?
- [ ] 인덱스를 새로 추가했다면 Alembic 마이그레이션 파일도 함께 작성했는가?
