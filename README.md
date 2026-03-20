# 📰 NewStrackers AI Server

자소서(PDF)와 지원 직무 정보를 기반으로 산업 뉴스를 매칭하고, RAG 기반 SWOT 분석과 면접 준비 리포트를 생성하는 FastAPI 서버입니다.

## 핵심 기능

- **리포트 생성**: PDF 자소서 + 지원 기업/직무/산업 → 뉴스 매칭 → SWOT + 최종 리포트 (비동기 Job)
- **뉴스 매칭**: pgvector 코사인 유사도 + pg_trgm 키워드 검색 → RRF 융합 + Cross-Encoder 재순위
- **비동기 Job 시스템**: PDF 업로드 즉시 job_id 반환 → 백그라운드 워커 처리 → 폴링으로 점진적 결과 수신
- **인증**: JWT Bearer 토큰 (선택적 — 비로그인 상태에서도 분석 가능)

## 기술 스택

| 분류              | 기술                                                        |
| ----------------- | ----------------------------------------------------------- |
| 언어 / 프레임워크 | Python 3.12, FastAPI                                        |
| LLM               | Anthropic Claude (`claude-sonnet-4-6` / `claude-haiku-4-5`) |
| 임베딩            | OpenAI `text-embedding-3-small` (1536차원)                  |
| DB                | PostgreSQL + pgvector + pg_trgm                             |
| 비동기 처리       | asyncio 기반 백그라운드 워커 (최대 3 동시 처리)             |
| 테스트            | Pytest                                                      |

## 설치

```bash
git clone <repo-url>
cd newstrackers-server
uv sync
```

## 환경 변수

```bash
cp .env.example .env
```

| 변수                | 필수 | 설명                     |
| ------------------- | ---- | ------------------------ |
| `DATABASE_URL`      | ✅    | PostgreSQL 연결 문자열   |
| `ANTHROPIC_API_KEY` | ✅    | Claude API 키            |
| `OPENAI_API_KEY`    | ✅    | 임베딩용 OpenAI 키       |
| `JWT_SECRET`        | ✅    | JWT 서명 시크릿 키       |
| `LOG_LEVEL`         | -    | 로그 레벨 (기본: `INFO`) |

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## DB 마이그레이션

```bash
alembic upgrade head   # 001 → 007 순서 자동 실행
```

## 실행

```bash
uvicorn app.main:app --reload
# Swagger UI: http://localhost:8000/docs
```

서버 시작 시 백그라운드 워커가 자동으로 함께 실행됩니다 (`app/main.py` lifespan).

## API 엔드포인트

### Health

| Method | Path             | 설명            |
| ------ | ---------------- | --------------- |
| GET    | `/health`        | 루트 헬스체크   |
| GET    | `/api/v1/health` | API v1 헬스체크 |

### 인증 (`/api/v1/auth`)

| Method | Path                    | 설명                       |
| ------ | ----------------------- | -------------------------- |
| POST   | `/api/v1/auth/register` | 회원가입 → JWT 반환        |
| POST   | `/api/v1/auth/login`    | 로그인 → JWT 반환          |
| GET    | `/api/v1/auth/me`       | 내 정보 조회 (Bearer 필요) |

### 분석 Job (`/api/v1/jobs`)

| Method | Path                               | 설명                                           |
| ------ | ---------------------------------- | ---------------------------------------------- |
| POST   | `/api/v1/jobs`                     | 분석 Job 생성 (PDF 업로드, 즉시 `job_id` 반환) |
| GET    | `/api/v1/jobs`                     | 내 Job 목록 조회                               |
| GET    | `/api/v1/jobs/{job_id}`            | Job 상태 + 점진적 결과 폴링                    |
| GET    | `/api/v1/jobs/reports`             | 완료된 리포트 목록                             |
| GET    | `/api/v1/jobs/reports/{report_id}` | 리포트 상세 조회                               |

#### Job 생성 예시

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -F "file=@자소서.pdf" \
  -F "company=삼성전자" \
  -F "job_title=SW개발" \
  -F "industry=반도체" \
  -F "career_level=신입"
```

응답:

```json
{
  "job_id": "550e8400-...",
  "status": "pending",
  "message": "분석 Job이 생성되었습니다."
}
```

#### 상태 폴링 예시

```bash
curl http://localhost:8000/api/v1/jobs/550e8400-...
```

응답:

```json
{
  "job_id": "550e8400-...",
  "status": "running",
  "progress_pct": 55,
  "partial_result": { "matched_news": [...] },
  "report_id": null
}
```

#### Job 상태 전이

```
pending ──► running ──► completed
                   └──► failed
```

## 프로젝트 구조

```
app/
  main.py                  # FastAPI 앱 진입점 + 워커 lifespan
  api/v1/
    router.py              # health / auth / jobs 라우터 통합
    endpoints/
      health.py            # 헬스체크
      auth.py              # 회원가입 / 로그인 / 내 정보
      jobs.py              # Job 생성 / 조회 / 리포트
  core/
    config.py              # 환경 변수 (pydantic-settings)
    dependencies.py        # DI 프로바이더 (싱글턴)
    auth.py                # JWT 검증 (get_optional_user_id)
    security.py            # 비밀번호 해싱, 토큰 생성
  db/
    base.py                # SQLAlchemy 엔진 / 세션
    models.py              # AnalysisJobDB, AnalysisReportDB, NewsArticleDB, NewsChunkDB
    user_models.py         # UserDB
    repositories/
      job_repository.py    # Job / Report CRUD
      news_repository.py   # 하이브리드 검색 쿼리
  schemas/
    data_models.py         # ResumeProfile, MatchedNewsItem, SWOTList, ReportResponse
    job_models.py          # JobCreateResponse, JobStatusResponse, ReportDetailResponse
    user.py                # UserRegister, UserLogin, TokenResponse
  services/
    report_pipeline.py     # ReportPipeline — 전체 분석 파이프라인 조율
    resume_analyzer.py     # PDF 파싱 + Haiku 기반 이력서 구조화
    report_generator.py    # Sonnet 기반 SWOT / 연관도 분석 / 최종 리포트 생성
    llm_client.py          # Claude API 래퍼 (_call_claude, stream_text)
    llm_service.py         # 하위 호환 파사드 + RAG 답변
    news_service.py        # 벡터·키워드 하이브리드 검색 + 재순위
    embedding_service.py   # OpenAI 임베딩 (text-embedding-3-small)
    worker.py              # 비동기 Job 워커 (asyncio, 3초 폴링)
    search/
      rrf.py               # RRF 융합 (k=60)
      reranker.py          # Cross-Encoder 재순위 (BAAI/bge-reranker-v2-m3)
alembic/
  versions/                # 001 ~ 007 마이그레이션
docs/                      # 상세 설계 문서 (00~07)
tests/
  unit/                    # 단위 테스트
  integration/             # 통합 테스트
```

## 테스트

```bash
# 전체
pytest -v

# 단위만
pytest tests/unit/ -v

# 커버리지
pytest --cov=app tests/
```

## 상세 문서

| 파일                               | 내용                                                    |
| ---------------------------------- | ------------------------------------------------------- |
| `docs/00_system_architecture.md`   | 전체 시스템 설계 및 레이어 구조                         |
| `docs/01_infra_env_spec.md`        | 환경 변수, DB 인덱스 전략                               |
| `docs/02_search_pipeline_spec.md`  | 벡터·키워드 하이브리드 검색 (V1~V3), RRF, Cross-Encoder |
| `docs/03_api_spec.md`              | API 엔드포인트 상세 명세                                |
| `docs/04_benchmark_spec.md`        | 검색 파이프라인 성능 벤치마크 실험 (E1~E4)              |
| `docs/05_report_jobs_spec.md`      | 비동기 Job 시스템, DB 스키마, 워커 동작                 |
| `docs/ASYNC_JOB_SYSTEM.md`         | Job 시스템 구현 기록 — 흐름, DB, 엔드포인트 예시        |
| `docs/ARCHITECTURE.md`             | 서비스 계층 리팩토링 기록 (Tier 1/2/3)                  |
| `docs/PIPELINE.md`                 | 오프라인 뉴스 데이터 처리 파이프라인 (Phase 1~5)        |
