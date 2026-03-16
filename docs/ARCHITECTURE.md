# Architecture & Refactoring Record

## 개요

이 문서는 newstrackers-server의 서비스 계층 구조와 2025년 3월 리팩토링 결정 사항을 기록한다.

---

## 계층 구조

```
HTTP Layer (FastAPI routers/endpoints)
    │
    ▼
Pipeline Layer (ReportPipeline)   ← Tier 1
    │
    ├── ResumeAnalyzer             ← Tier 2
    ├── ReportGenerator            ← Tier 2
    └── NewsService
            │
            └── EmbeddingService   ← Tier 3
```

---

## 서비스 클래스 역할

| 클래스 | 파일 | 역할 |
|--------|------|------|
| `LLMClient` | `services/llm_client.py` | Claude API 기반 호출 (`_call_claude`, `_call_model`, `_extract_json`, `stream_text`) |
| `ResumeAnalyzer` | `services/resume_analyzer.py` | 자소서 분석 (`analyze_resume`) + 검색 쿼리 최적화 (`transform_query`) — Haiku 사용 |
| `ReportGenerator` | `services/report_generator.py` | SWOT, 산업 연관성, 최종 리포트 생성 — Sonnet 사용 |
| `LLMService` | `services/llm_service.py` | 하위 호환 파사드 + RAG 답변, 기업 분석 레거시 메서드 |
| `EmbeddingService` | `services/embedding_service.py` | OpenAI text-embedding-3-small 벡터화 |
| `NewsService` | `services/news_service.py` | 하이브리드 검색 오케스트레이션 (벡터 + pg_trgm → RRF → Cross-Encoder) |
| `ReportPipeline` | `services/report_pipeline.py` | 리포트 생성 전체 파이프라인 오케스트레이션 |

---

## DI 체인 (`app/core/dependencies.py`)

```
get_embedding_service()          → EmbeddingService()
get_llm_client()                 → LLMClient()
get_resume_analyzer()            → ResumeAnalyzer()
get_report_generator()           → ReportGenerator()
get_news_service()               → NewsService(embedding_service=get_embedding_service())
get_llm_service()                → LLMService()  ← backward-compat
get_report_pipeline()            → ReportPipeline(
                                       news_service=get_news_service(),
                                       resume_analyzer=get_resume_analyzer(),
                                       report_generator=get_report_generator(),
                                   )
```

모든 provider는 `@lru_cache` 싱글턴.

---

## 엔드포인트 책임 분리

| 엔드포인트 | 파일 | HTTP 책임 | 비즈니스 로직 위임 대상 |
|-----------|------|-----------|----------------------|
| `POST /analysis/report` | `endpoints/analysis.py` | 파일 수신, 유효성 검사, PDF 파싱 | `ReportPipeline.run()` |
| `POST /analysis/report/stream` | `endpoints/analysis.py` | 파일 수신, 유효성 검사, PDF 파싱, Step 1 SSE 이벤트 | `ReportPipeline.stream()` |
| `POST /search` | `endpoints/search.py` | 요청 수신, 실험 로그 | `LLMService`, `NewsService` |
| `POST /resume/analyze` | `endpoints/resume.py` | 파일 수신, 유효성 검사 | `LLMService.analyze_resume()` |

---

## 리팩토링 배경 (2025-03-09)

### 문제: God Service

`LLMService` 단일 클래스에 18개 메서드가 집중되어 있었다:
- Haiku 기반 빠른 분석 (analyze_resume, transform_query)
- Sonnet 기반 리포트 생성 (swot_list, relevance_analysis, final_report)
- RAG 검색 답변 (generate_rag_answer)
- 레거시 분석 (extract_trends, keywords, 기업 SWOT, 면접 질문)
- 스트리밍 (stream_text, stream_industry_trends, stream_swot)

또한 `analysis.py` 엔드포인트에 파이프라인 오케스트레이션 로직이 직접 포함되어 있어
`/report`와 `/report/stream` 간 코드 중복이 있었다.

### 해결: 3 Tier 리팩토링

**Tier 1 — 파이프라인 추출**
- `services/report_pipeline.py` 생성
- `ReportPipeline.run()` (동기) + `ReportPipeline.stream()` (비동기 AsyncGenerator)
- `endpoints/analysis.py`는 HTTP 관심사만 담당하는 얇은 핸들러로 축소 (~120줄)

**Tier 2 — LLMService 분리**
- `services/llm_client.py`: Claude API 기반 호출 레이어
- `services/resume_analyzer.py`: Haiku 기반 자소서 분석 + 쿼리 최적화
- `services/report_generator.py`: Sonnet 기반 리포트 생성 3종
- `LLMService`는 하위 호환 파사드로 유지 (위임 + 레거시 메서드)

**Tier 3 — 임베딩 서비스 분리 + 명시적 DI**
- `services/embedding_service.py`: OpenAI 임베딩 전용 클래스
- `NewsService`는 `EmbeddingService`를 주입받아 사용
- `dependencies.py`에 명시적 DI 체인 구성 (`@lru_cache` 싱글턴)

---

## 구현 완료 — 비동기 Job 시스템 (2026-03-12)

**DB Job Table + Worker 패턴** 구현 완료. 상세 명세: `docs/05_report_jobs_spec.md`

```
POST /api/v1/jobs         → job_id 즉시 반환 (PDF 파싱만 수행)
Worker (asyncio, 3초 폴링) → ReportPipeline.stream() 실행, DB에 결과 저장
GET  /api/v1/jobs/{id}    → DB에서 상태 조회 (폴링)
GET  /api/v1/jobs/{id}/stream → SSE 재접속 가능
GET  /api/v1/jobs/reports/{id} → 완료된 리포트 조회
```

- 구현 방식: FastAPI `lifespan` 내 `asyncio.create_task` (단일 프로세스, Redis 불필요)
- 결과 저장: `analysis_jobs` + `analysis_reports` 테이블 (Alembic migration 004)
- 인증: JWT Bearer token (`app/core/auth.py` — `get_optional_user_id`)
- 기존 `/report/stream` 엔드포인트 병렬 유지 (비로그인 단발성 사용)
