# NewsTrackers AI Server

이력서 PDF와 뉴스 데이터베이스를 결합해 취업 준비용 분석 리포트를 생성하는 FastAPI 서버입니다. 현재 코드는 "요청 즉시 응답" 방식이 아니라, PDF 업로드로 분석 job을 생성하고 worker가 비동기로 처리한 뒤 리포트를 조회하는 구조입니다.

## 핵심 기능

- PDF 이력서 텍스트 추출 및 AI 기반 프로필 분석
- 뉴스 벡터 검색 + 키워드 검색을 결합한 하이브리드 매칭
- SWOT, 산업 연관성 분석, 최종 면접 준비 리포트 생성
- JWT 기반 회원가입 / 로그인
- DB polling 기반 비동기 job worker

## 기술 스택

| 분류 | 기술 |
|------|------|
| API | FastAPI, Uvicorn |
| 언어 | Python 3.10+ |
| DB | PostgreSQL, SQLAlchemy, Alembic, pgvector |
| LLM | Anthropic Claude |
| Embedding | OpenAI `text-embedding-3-small` |
| 검색 | Vector similarity + BM25 + RRF |
| 테스트 | Pytest |

## 빠른 시작

### 1. 의존성 설치

```bash
uv sync
```

### 2. PostgreSQL 실행

```bash
docker compose up -d db
```

기본 로컬 DB 접속 정보:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/newstrackers
```

### 3. 환경 변수 설정

```bash
cp .env.example .env
```

필수 변수:

| 변수 | 필수 | 설명 |
|------|------|------|
| `DATABASE_URL` | ✅ | PostgreSQL 연결 문자열 |
| `ANTHROPIC_API_KEY` | ✅ | 리포트 생성용 Claude API 키 |
| `OPENAI_API_KEY` | ✅ | 임베딩 / 검색용 OpenAI API 키 |
| `SECRET_KEY` | 권장 | JWT 서명 키 |

자주 쓰는 선택 변수:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `RUN_WORKER_IN_API` | `True` | API 프로세스 안에서 worker 자동 실행 |
| `WORKER_POLL_INTERVAL_SEC` | `3.0` | pending job polling 주기 |
| `WORKER_MAX_CONCURRENT` | `3` | 동시 처리 job 수 |
| `EXPERIMENT_USE_FAKE_PIPELINE` | `False` | 외부 API 없이 fake pipeline 사용 |
| `LOG_LEVEL` | `INFO` | 로그 레벨 |
| `LOG_FILE` | `./logs/app.log` | 로그 파일 경로 |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS 허용 origin |

### 4. 마이그레이션 적용

```bash
uv run alembic upgrade head
```

### 5. 서버 실행

기본 모드: API와 worker를 한 프로세스에서 함께 실행합니다.

```bash
uv run uvicorn app.main:app --reload
```

분리 모드가 필요하면:

```bash
RUN_WORKER_IN_API=false uv run uvicorn app.main:app --reload
uv run python -m app.worker_main
```

문서:

- Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## API 개요

기본 prefix는 `/api/v1` 입니다.

### Health

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 루트 헬스체크 |
| GET | `/api/v1/health` | API 헬스체크 |

### Auth

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/auth/register` | 회원가입 후 access token 반환 |
| POST | `/api/v1/auth/login` | 로그인 후 access token 반환 |
| GET | `/api/v1/auth/me` | 현재 사용자 조회 |

`/auth/me` 는 Bearer 토큰이 필요합니다.

### Jobs / Reports

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/jobs` | PDF 이력서 업로드 후 분석 job 생성 |
| GET | `/api/v1/jobs` | 로그인 사용자의 job 목록 조회 |
| GET | `/api/v1/jobs/{job_id}` | 개별 job 상태 조회 |
| GET | `/api/v1/jobs/reports` | 로그인 사용자의 리포트 목록 조회 |
| GET | `/api/v1/jobs/reports/{report_id}` | 리포트 상세 조회 |

`POST /api/v1/jobs` 요청 필드:

- `file`: PDF 파일, 최대 5MB
- `company`: 지원 회사명
- `job_title`: 지원 직무
- `industry`: 산업명
- `career_level`: `신입` 또는 `경력`

주의:

- `POST /api/v1/jobs` 는 토큰 없이도 호출할 수 있습니다.
- `GET /api/v1/jobs`, `GET /api/v1/jobs/reports` 는 토큰이 없으면 빈 목록을 반환합니다.
- worker가 실행 중이지 않으면 job은 `pending` 상태에 머뭅니다.

## 사용 예시

### 1. 회원가입

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "demo@example.com",
    "nickname": "demo",
    "password": "password1234"
  }'
```

### 2. 로그인

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "demo@example.com",
    "password": "password1234"
  }'
```

응답의 `access_token` 을 이후 요청에 사용합니다.

### 3. 분석 job 생성

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -F "file=@resume_kimjinju.pdf" \
  -F "company=삼성전자" \
  -F "job_title=백엔드 개발자" \
  -F "industry=반도체" \
  -F "career_level=신입"
```

예상 응답:

```json
{
  "job_id": "7e4c2c8c-4fe6-4ec2-a665-bc58a4b99a8b",
  "status": "pending",
  "message": "분석 요청이 접수되었습니다. GET /jobs/{job_id} 로 진행상황을 확인하세요."
}
```

### 4. job 상태 폴링

```bash
curl http://localhost:8000/api/v1/jobs/<JOB_ID>
```

응답에는 다음 정보가 포함됩니다.

- `status`: `pending` | `running` | `completed` | `failed`
- `progress_pct`: 진행률
- `retry_count`: 자동 재시도 횟수
- `report_id`: 완료 시 리포트 ID
- `timing`: queue wait / processing / total lead time

### 5. 리포트 조회

```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" \
  http://localhost:8000/api/v1/jobs/reports
```

```bash
curl http://localhost:8000/api/v1/jobs/reports/<REPORT_ID>
```

리포트 상세 응답에는 다음 데이터가 포함됩니다.

- `resume_profile`
- `matched_news`
- `matched_news_count`
- `relevance_analysis`
- `swot`
- `final_report`

## Worker 동작 방식

worker는 DB에서 `pending` job을 polling 하며 `ReportPipeline` 을 실행합니다.

진행률은 파이프라인 단계에 맞춰 갱신됩니다.

- 25%: 이력서 분석 완료
- 30%: 검색 쿼리 최적화 완료
- 55%: 뉴스 검색 완료
- 80%: SWOT / 산업 연관성 분석 완료
- 100%: 최종 리포트 생성 완료

실패 시 최대 3회까지 자동 재시도합니다.

## 테스트

```bash
uv run pytest -v
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run pytest --cov=app tests/
```

추가 테스트 / 벤치마크 예시는 `TESTING.md` 에 정리되어 있습니다.

## 프로젝트 구조

```text
app/
  api/v1/endpoints/
    auth.py           # 회원가입 / 로그인 / 내 정보
    health.py         # 헬스체크
    jobs.py           # job 생성, 상태 조회, 리포트 조회
  core/
    auth.py           # optional JWT 인증
    config.py         # 환경 변수 설정
    dependencies.py   # DI 및 worker 싱글톤 구성
    security.py       # 비밀번호 해시 / JWT 발급
  db/
    base.py           # SQLAlchemy engine / session
    models.py         # 뉴스, job, report 모델
    user_models.py    # 사용자 모델
    repositories/
      job_repository.py
  services/
    news_service.py
    resume_analyzer.py
    report_generator.py
    report_pipeline.py
    worker.py
  main.py             # FastAPI 진입점
  worker_main.py      # standalone worker 진입점
alembic/              # DB migrations
docker-compose.yml    # 로컬 PostgreSQL
tests/                # unit / integration tests
scripts/              # 데이터 적재, 실험, 벤치마크 스크립트
```
