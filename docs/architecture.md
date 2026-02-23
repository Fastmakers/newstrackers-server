# News Tracker Server - 아키텍처 문서

## 프로젝트 개요

취업 지원자가 자소서(PDF)를 업로드하면, 매일 수집된 산업군 뉴스 데이터를 RAG(Retrieval-Augmented Generation)로 활용하여 산업 동향 분석, 관련 뉴스 매칭, SWOT 분석, 종합 취업 리포트를 자동으로 생성하는 FastAPI 서버입니다.

---

## 기술 스택

| 구분 | 기술 | 용도 |
|------|------|------|
| 웹 프레임워크 | FastAPI | REST API 서버 |
| ASGI 서버 | Uvicorn | FastAPI 실행 |
| LLM 파이프라인 | LangGraph | 4단계 분석 그래프 |
| LLM | Claude API (Anthropic, Sonnet 4.5) | 자소서 분석, 트렌드 분석, SWOT, 리포트 생성 |
| PDF 파싱 | PyMuPDF (fitz) | 자소서 텍스트 추출 (Korean CJK 최적) |
| 벡터 DB | PostgreSQL + pgvector | 뉴스 임베딩 유사도 검색 (읽기 전용) |
| 임베딩 모델 | OpenAI text-embedding-3-small | 쿼리 임베딩 생성 (1536차원) |
| DB 드라이버 | asyncpg | PostgreSQL 비동기 연결 |
| 설정 관리 | pydantic-settings | .env 파일 기반 설정 |

---

## 디렉토리 구조

```
newstrakers-server/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI 앱 진입점
│   ├── core/
│   │   └── config.py                    # 환경 설정 (Settings)
│   ├── api/
│   │   └── v1/
│   │       ├── router.py                # API 라우터 등록
│   │       └── endpoints/
│   │           ├── news.py              # 뉴스 수집/검색 엔드포인트
│   │           └── analysis.py          # 자소서 분석 엔드포인트
│   ├── services/
│   │   ├── vector_store.py              # pgvector 벡터 검색 (읽기 전용)
│   │   ├── claude_llm.py                # Claude API 클라이언트
│   │   └── pdf_extractor.py             # PDF 텍스트 추출
│   └── agents/
│       ├── state.py                     # LangGraph AnalysisState 정의
│       ├── analysis_graph.py            # 파이프라인 조립 및 싱글톤
│       └── nodes/
│           ├── analyze_resume.py        # Node 1: 자소서 분석
│           ├── match_keywords.py        # Node 2: 키워드 매칭
│           ├── analyze_relevance.py     # Node 3: 관련성 분석
│           └── generate_report.py       # Node 4: 리포트 생성
├── docs/                                # 프로젝트 문서
├── pyproject.toml
└── .env.example
```

---

## 핵심 흐름: 자소서 분석 (LangGraph 파이프라인)

사용자가 PDF를 업로드하면 4단계 파이프라인이 순차 실행됩니다.

```
POST /api/v1/analysis/report (PDF 업로드)
         │
         ▼ pdf_extractor.py
[PyMuPDF로 텍스트 추출]
         │
         ▼ LangGraph ainvoke()
┌────────────────────────────────────────────┐
│                                            │
│  Node 1: analyze_resume                    │
│  Claude → JSON 파싱                         │
│  {job_title, industry, company,            │
│   skills, experiences}                     │
│          │                                 │
│          ▼                                 │
│  Node 2: match_keywords                    │
│  쿼리 5개 × pgvector 검색                   │
│  중복 제거 → 유사도 정렬 → 최대 15건         │
│          │                                 │
│          ▼                                 │
│  Node 3: analyze_relevance                 │
│  Claude → 산업 동향 + 지원자 연관성 분석     │
│          │                                 │
│          ▼                                 │
│  Node 4: generate_report                   │
│  Claude 1차: SWOT (JSON)                   │
│  Claude 2차: 종합 마크다운 리포트            │
│                                            │
└────────────────────────────────────────────┘
         │
         ▼
JSON 응답: resume_profile + matched_news +
          relevance_analysis + swot + final_report
```

---

## DB 스키마

뉴스 데이터는 팀에서 사전에 구축한 `news_article_embeddings` 테이블을 **읽기 전용**으로 사용합니다.

```sql
-- 사전 구축된 테이블 (이 서버에서 생성/변경하지 않음)
CREATE TABLE news_article_embeddings (
    id               SERIAL PRIMARY KEY,
    content_hash     TEXT,
    content          TEXT,              -- 기사 본문 (document로 매핑)
    embedding        vector(1536),      -- text-embedding-3-small 임베딩
    doc_id           TEXT,
    context_id       TEXT,
    doc_title        TEXT,              -- 기사 제목
    doc_source       TEXT,              -- 원본 URL
    doc_published    TEXT,              -- 기사 발행일 (텍스트)
    doc_class_code   TEXT,              -- 산업 분류 코드
    dataset_identifier TEXT,
    data_split       TEXT,
    source_file      TEXT,
    raw_meta         JSON,
    created_at       TIMESTAMPTZ
);
```

---

## LangGraph 상태 (AnalysisState)

```python
class AnalysisState(TypedDict):
    resume_text: str                         # PDF 추출 텍스트 (입력)
    resume_profile: Optional[ResumeProfile]  # Node 1 → 직무/산업/회사/스킬/경험
    matched_news: Optional[list[dict]]       # Node 2 → pgvector 검색 결과
    relevance_analysis: Optional[str]        # Node 3 → 산업 동향 + 연관성 분석
    swot: Optional[dict[str, list[str]]]     # Node 4 → SWOT 분석
    final_report: Optional[str]              # Node 4 → 종합 마크다운 리포트
    error: Optional[str]                     # 에러 메시지 (None = 성공)
```
