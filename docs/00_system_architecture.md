# 00_system_architecture.md — 시스템 전체 구조 및 공통 원칙

> **이 문서는 모든 AI 에이전트가 작업 전 반드시 읽어야 하는 최우선 컨텍스트입니다.**
> 다른 어떤 명세서보다 이 문서의 규칙이 우선합니다.

---

## 1. Project Overview

| 항목 | 내용 |
|------|------|
| **프로젝트명** | NewsTrackers AI Server |
| **목표** | 매일경제 뉴스 기반 취업 준비 AI 서비스 — 산업 트렌드 분석 + 기업 SWOT + 면접 Q&A |
| **데이터 소스** | 매일경제 2025년 전체 기사 (news_articles 188,379건) |
| **운영 환경** | AWS RDS PostgreSQL + FastAPI (uvicorn) |

---

## 2. Tech Stack

| 레이어 | 기술 | 버전/모델 |
|--------|------|-----------|
| **API** | FastAPI + Uvicorn | `>=0.115.0` |
| **ORM** | SQLAlchemy | `>=2.0.0` |
| **DB** | PostgreSQL (AWS RDS) | pgvector 확장 필수 |
| **벡터 검색** | pgvector (`<=>` cosine distance) | dim=1536 |
| **키워드 검색** | pg_trgm (`word_similarity`) | GIN 인덱스 필수 |
| **LLM (분석)** | Claude `claude-sonnet-4-6` | Anthropic SDK |
| **임베딩** | OpenAI `text-embedding-3-small` | dim=1536 |
| **형태소 분석** | kiwipiepy | `>=0.18.0` |
| **리랭킹** | `BAAI/bge-reranker-v2-m3` | sentence-transformers |
| **스키마 마이그레이션** | Alembic | `>=1.13.0` |

---

## 3. 전체 아키텍처

시스템은 **실시간 API 파이프라인 2개**와 **오프라인 배치 파이프라인 1개**로 구성된다.

### 3-1. 공통 인프라 레이어

```
              ┌────────────────────────────────────────────┐
              │         FastAPI  app/api/v1/endpoints/     │
              │  analysis.py  search.py  resume.py         │
              └──────────────────┬─────────────────────────┘
                                 │ Depends()
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
   │  NewsService    │  │  LLMService     │  │  NewsRepository  │
   │  V1 vector_     │  │  Claude 호출    │  │  search_by_      │
   │  V2 hybrid_     │  │  SSE 스트리밍   │  │  vector/trgm     │
   │  V3 rerank_     │  │  analyze_resume │  │  get_by_keyword  │
   └────────┬────────┘  └─────────────────┘  └────────┬─────────┘
            │ ThreadPoolExecutor                       │
            │ (embed ‖ keyword → vector → RRF → rerank)│
            └──────────────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
   │ pgvector (HNSW) │  │ pg_trgm (GIN)   │  │ OpenAI Embedding │
   │ cosine distance │  │ word_similarity  │  │ text-embedding-  │
   │ news_chunks     │  │ news_chunks      │  │ 3-small (1536d)  │
   └────────┬────────┘  └────────┬─────────┘  └──────────────────┘
            └──────────────┬─────┘
                           ▼
              ┌────────────────────────┐
              │   PostgreSQL (AWS RDS) │
              │   news_articles 188,379│
              │   news_chunks   335,073│
              └────────────────────────┘
```

---

### 3-2. [Pipeline C] 자소서 단독 분석 — `POST /resume/analyze`

```
Request: PDF / DOCX 파일 (multipart)
         │
         ▼
_extract_text_from_pdf() | _extract_text_from_docx()
         │  텍스트 추출 (최대 5,000자)
         ▼
llm_service.analyze_resume(text)    ← 뉴스 검색 없음
         │
         ▼
Response: ResumeAnalysis
          { skills, experience_keywords, target_role,
            strengths, search_keywords }
```

---

### 3-3. [Pipeline E] 종합 리포트 — `POST /analysis/report` (프론트엔드 전용)

```
Request: multipart/form-data
         file (PDF), industry, company, job_title
         │
         ▼
[1] _extract_text_from_pdf()         ← 최대 5 MB, PDF만 허용
         │
         ▼
[2] llm_service.analyze_resume()     ← Claude Haiku
         │  skills, experience_keywords, target_role, search_keywords
         ▼
[3] ResumeProfile 구성 (Form 파라미터 우선, 없으면 자소서 분석 결과)
         │
         ▼
[4] llm_service.transform_query()    ← Claude Haiku
         │  검색 최적화 쿼리 생성
         ▼
[5] news_service.hybrid_search(query, keyword_query, top_k=15)
         │  Vector ‖ pg_trgm → RRF → Top 15
         │  → MatchedNewsItem[]
         ▼
[6] ThreadPoolExecutor(max_workers=3) — 2개 병렬
         ├─► generate_swot_list(resume, company, job_title, chunks, industry)
         │       → Dict[str, List[str]]  ← 지원자 관점 SWOT
         └─► generate_relevance_analysis(resume, chunks, company, industry, job_title)
                 → markdown string
         │
         ▼
[7] generate_final_report(resume, company, job_title, industry, swot, news_titles)
         → markdown string
         │
         ▼
Response: ReportResponse
          { resume_profile, matched_news, matched_news_count,
            relevance_analysis, swot (SWOTList), final_report }
```

---

### 3-6. [Pipeline D] 오프라인 NLP 배치 — `scripts/run_pipeline.py`

```
실시간 API와 완전히 분리 — 서버 실행 없이 독립 실행

news_articles DB
         │
         ▼  Phase 1: 데이터 품질 필터  (app/analysis/)
         │  text_cleaner.py          ← Regex 노이즈 제거
         │  lexical_diversity.py     ← LogTTR 노이즈 탐지 (min_tokens=50)
         │  → data/lexical_diversity.json  (noise_article_ids 15,037건)
         │
         ▼  Phase 2: NLP 분석  (app/analysis/)
         │  ngram_extractor.py       ← TF-IDF N-gram 키워드
         │  ner_extractor.py         ← NER/POS (ORG/PERSON/LOC/동사)
         │  → data/ngrams.json
         │  → data/ner_result.json
         │
         ▼  Phase 3: 벡터 임베딩 (이미 완료)
         │  OpenAI text-embedding-3-small (dim=1536)
         │  → news_chunks 335,073건
```

> `app/analysis/industry_analyzer.py`, `company_analyzer.py` — 삭제 완료.

---

## 4. 레이어별 책임 경계

| 레이어 | 책임 O | 책임 X |
|--------|--------|--------|
| **Endpoint** | HTTP 요청 파싱, 응답 직렬화, HTTP 에러 변환 | 비즈니스 로직, DB 접근 |
| **Service** | 검색 오케스트레이션, LLM 호출, 병렬 실행 | 직접 SQL 작성 |
| **Repository** | SQL 쿼리 캡슐화, ORM 사용 | 비즈니스 판단 |
| **Adapter** | DB Row → Domain Model 변환 | 외부 API 호출 |
| **Domain Model** | 데이터 구조 정의 (Pydantic) | 부작용(side effect) |

---

## 5. 검색 파이프라인 버전 (V1 / V2 / V3)

| 버전 | 방식 | 사용 위치 |
|------|------|-----------|
| **V1** | 벡터 검색 + title 기업명 보너스 | `vector_search()` |
| **V2** | 벡터 ‖ pg_trgm 병렬 → RRF | `hybrid_search()` |
| **V3** | V2 + Cross-Encoder 리랭킹 | `rerank_chunks()` |

> 상세 스펙: `docs/02_search_pipeline_spec.md`

---

## 6. 엔드포인트 목록

| 엔드포인트 | 방식 | 사용 |
|------------|------|------|
| `POST /analysis/report` | 배치 JSON | **프론트엔드 전용** |
| `POST /resume/analyze` | 배치 JSON | 자소서 단독 분석 |
| `POST /resume/parse` | 배치 JSON | 텍스트 추출만 |
| `POST /search` | 배치 JSON | RAG 검색 직접 호출 |
| `GET /health` | JSON | 헬스체크 |

---

## 7. Global AI Coding Rules (Agent 필수 지시사항)

AI 에이전트가 이 프로젝트에서 코드를 작성/수정할 때 반드시 따라야 하는 규칙입니다.

### 7-1. 명세서 우선 원칙 (Single Source of Truth)
- 코드 작성 전 반드시 관련 명세서 파일을 읽는다.
- 명세서에 없는 동작을 임의로 구현하지 않는다.
- 명세서 변경이 필요하면 코드 수정 전에 문서를 먼저 업데이트한다.

### 7-2. 환경 변수 하드코딩 금지
```python
# ❌ 금지
DATABASE_URL = "postgresql://user:pass@prod-db.rds.amazonaws.com:5432/newsdb"
ANTHROPIC_API_KEY = "sk-ant-..."

# ✅ 올바른 방법
from app.core.config import settings
db_url = settings.DATABASE_URL
```

### 7-3. 레이어 경계 위반 금지
```python
# ❌ Endpoint에서 직접 DB 접근
@router.get("/articles")
def get_articles(db: Session = Depends(get_db)):
    return db.query(NewsArticleDB).all()  # Repository를 거치지 않음

# ✅ Repository를 통해 접근
@router.get("/articles")
def get_articles(news_service: NewsService = Depends(get_news_service)):
    return news_service.get_articles(query="...")
```

### 7-4. 도메인 모델 필드명 규칙
```python
# ❌ 구 필드명 (사용 금지 — backward-compat property가 있으나 신규 코드에서는 사용 금지)
article.content    # → article.body 사용
article.source     # → article.source_name 사용
article.category   # → article.category_l2 사용

# ✅ 현행 필드명
article.body
article.source_name
article.category_l2
```

### 7-5. 병렬 실행 원칙
- 독립적인 I/O 작업(DB 쿼리, API 호출)은 `ThreadPoolExecutor`로 병렬화한다.
- 각 병렬 작업은 **독립적인 DB 세션**을 사용한다 (세션 공유 금지).
- `asyncio`와 sync SQLAlchemy를 혼용하지 않는다.

### 7-6. 에러 처리 원칙
- Service 레이어: 에러를 로깅 후 빈 결과(`[]`, `{}`) 반환 (Fail-Safe).
- Endpoint 레이어: Service 에러를 적절한 HTTP 코드로 변환 (Fail-Fast).
- LLM 호출 실패: 재시도 없이 즉시 fallback 텍스트 반환.

### 7-7. 테스트 작성 원칙
- 새 기능 추가 시 `tests/unit/` 에 단위 테스트를 함께 작성한다.
- Live API 호출 테스트는 `@pytest.mark.live` 마커를 사용한다.
- `pytest -m "not live"` 로 항상 통과해야 한다.

---

## 8. 문서 읽기 순서 (AI Agent용)

새 작업을 시작할 때 아래 순서로 문서를 읽는다:

1. **`docs/00_system_architecture.md`** (이 파일) — 전체 구조 파악
2. **`docs/01_infra_env_spec.md`** — 환경 변수 및 DB 연결 설정
3. 작업 영역에 따라 선택:
   - 검색 관련 → `docs/02_search_pipeline_spec.md`
   - API 관련 → `docs/03_api_spec.md`
   - 성능 실험 → `docs/04_benchmark_spec.md`
   - 데이터 파이프라인 → `docs/PIPELINE.md`

---

## 9. 주요 파일 위치

### 실시간 API (온라인)

| 파일 | 역할 | Pipeline |
|------|------|----------|
| `app/core/config.py` | Pydantic Settings — 환경 변수 로딩 | 공통 |
| `app/core/dependencies.py` | FastAPI Depends — 서비스 인스턴스 제공 | 공통 |
| `app/db/base.py` | SQLAlchemy 엔진 + SessionLocal | 공통 |
| `app/db/models.py` | ORM (NewsArticleDB, NewsChunkDB) | 공통 |
| `app/db/adapters/news_adapter.py` | DB Row → Domain Model 변환 | 공통 |
| `app/db/repositories/news_repository.py` | SQL 쿼리 (vector/trgm/ilike) | A, B |
| `app/schemas/data_models.py` | Pydantic 도메인 모델 전체 | 공통 |
| `app/services/news_service.py` | V1/V2/V3 검색 오케스트레이션 | A, B |
| `app/services/llm_service.py` | Claude 호출 (분석 + 스트리밍) | C, E |
| `app/services/search/rrf.py` | RRF 융합 (k=60) | E |
| `app/services/search/reranker.py` | Cross-Encoder V3 (lazy-load) | - |
| `app/api/v1/endpoints/analysis.py` | Pipeline E — `/report` (프론트 전용) | E |
| `app/api/v1/endpoints/resume.py` | Pipeline C — 자소서 단독 | C |
| `app/api/v1/endpoints/search.py` | RAG 검색 직접 호출 | - |

### 오프라인 배치 (Pipeline D)

| 파일 | 역할 |
|------|------|
| `app/analysis/text_cleaner.py` | Regex 노이즈 제거 |
| `app/analysis/lexical_diversity.py` | LogTTR 노이즈 탐지 |
| `app/analysis/ngram_extractor.py` | TF-IDF N-gram 키워드 |
| `app/analysis/ner_extractor.py` | NER/POS 개체명 인식 |
| `scripts/run_pipeline.py` | Phase 1~3 통합 실행 |
| `scripts/benchmark_search.py` | 검색 성능 벤치마크 (E1~E4) |
| `data/lexical_diversity.json` | 노이즈 기사 ID 목록 |
| `data/ngrams.json` | 카테고리별 키워드 |
| `data/ner_result.json` | ORG·PERSON·LOC·동사 |

