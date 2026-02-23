# 설치 및 실행 가이드

## 사전 요구사항

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 패키지 매니저
- PostgreSQL 15+ (pgvector 확장 포함)
- Anthropic API 키 ([발급 페이지](https://console.anthropic.com/))
- OpenAI API 키 ([발급 페이지](https://platform.openai.com/api-keys))

---

## PostgreSQL + pgvector 설정

### macOS (Homebrew)

```bash
# PostgreSQL 설치
brew install postgresql@15

# pgvector 확장 설치
brew install pgvector

# PostgreSQL 시작
brew services start postgresql@15

# 데이터베이스 생성
createdb newstracker
```

### Docker (권장)

```bash
docker run -d \
  --name newstracker-db \
  -e POSTGRES_DB=newstracker \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

> pgvector Docker 이미지는 pgvector 확장이 미리 설치되어 있습니다.

---

## 설치

```bash
# 1. 저장소 클론
git clone <repository-url>
cd newstrakers-server

# 2. 의존성 설치
uv sync

# 3. 환경 변수 설정
cp .env.example .env
# .env 파일을 열고 실제 API 키 및 DB URL 입력
```

---

## 환경 변수 설정

`.env` 파일에 다음 값들을 설정합니다:

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | O | Claude API 키 (자소서 분석 / 리포트 생성) |
| `OPENAI_API_KEY` | O | OpenAI API 키 (쿼리 임베딩 생성 — text-embedding-3-small) |
| `DATABASE_URL` | X | PostgreSQL 접속 URL (기본: `postgresql://postgres:postgres@localhost:5432/newstracker`) |

---

## 실행

```bash
# 개발 서버 실행
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

서버가 시작되면:
- API 문서: http://localhost:8000/docs (Swagger UI)
- 헬스 체크: http://localhost:8000/health

---

## 개발 도구

```bash
# 린터/포매터 실행
uv run ruff check .
uv run ruff format .

# 테스트 실행
uv run pytest
```
