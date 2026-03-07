# 03_api_spec.md — API 엔드포인트 명세

> **Single Source of Truth for all API endpoints.**
> 프론트엔드 연동 엔드포인트 / 내부 서비스 엔드포인트 / 데이터 모델 전체 포함.

---

## 1. 프론트엔드 연동 엔드포인트

프론트엔드가 실제로 호출하는 엔드포인트는 **하나**입니다.

### POST `/api/v1/analysis/report`

자소서 PDF를 업로드하면 산업 뉴스 기반 종합 취업 전략 리포트를 반환합니다.

#### Request (multipart/form-data)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | File (PDF) | ✅ | 자소서 PDF 파일 (최대 5 MB) |
| `industry` | string | 선택 | 희망 산업군 (예: `반도체`, `AI 인공지능`) |
| `company` | string | 선택 | 목표 기업 (예: `삼성전자`) |
| `job_title` | string | 선택 | 희망 직무 (예: `백엔드 개발자`) |
| `include_raw_news` | string | 선택 | `"true"` 고정 (프론트 하드코딩, 서버에서 무시) |
| `report_mode` | string | 선택 | `"fast"` 고정 (프론트 하드코딩, 서버에서 무시) |

> `company`, `job_title`, `industry` 가 Form에 없으면 자소서 분석 결과에서 자동 추론합니다.

#### Response (JSON) — `ReportResponse`

```json
{
  "resume_profile": {
    "company": "삼성전자",
    "job_title": "백엔드 개발자",
    "industry": "반도체",
    "skills": ["Python", "FastAPI", "PostgreSQL"],
    "experiences": ["3년 백엔드 개발 경험", "MSA 설계 및 운영"]
  },
  "matched_news": [
    {
      "id": 1234,
      "title": "삼성전자 HBM3E 양산 확대",
      "job_category": "IT/기술",
      "published_at": "2026-02-15T09:00:00",
      "url": "https://example.com/news/1234",
      "distance": 0.18
    }
  ],
  "matched_news_count": 15,
  "relevance_analysis": "### 산업 트렌드 요약\n...\n### 역량 연결 포인트\n...",
  "swot": {
    "strengths": ["핵심 강점 1", "핵심 강점 2"],
    "weaknesses": ["약점 1"],
    "opportunities": ["기회 1"],
    "threats": ["위협 1"]
  },
  "final_report": "## 면접 준비 포인트\n...\n## 최종 권고사항\n..."
}
```

> **SWOT 방향**: 지원자(자소서 작성자) 관점 SWOT — 해당 기업에 지원했을 때의 강점/약점/기회/위협.
> 기업 자체의 SWOT 분석이 아닙니다.

#### 파이프라인 단계

```
[1] PDF 파싱
    → pypdf로 텍스트 추출 (최대 파일 크기: 5 MB)

[2] 자소서 분석 — analyze_resume() (Claude Haiku)
    → skills: List[str]              — 핵심 기술 스킬
    → experience_keywords: List[str] — 경험 키워드
    → target_role: str               — 희망 직무
    → strengths: List[str]           — 강점
    → search_keywords: List[str]     — 뉴스 검색 키워드

[3] ResumeProfile 구성
    → company:    Form 파라미터 우선
    → job_title:  Form 파라미터 우선, 없으면 analyze_resume.target_role
    → industry:   Form 파라미터 우선
    → skills:     analyze_resume.skills
    → experiences: analyze_resume.experience_keywords

[4] 쿼리 변환 — transform_query() (Claude Haiku)
    → 자소서 + company + job_title → 뉴스 검색 최적화 쿼리

[5] 하이브리드 검색 — hybrid_search(query, keyword_query, top_k=15)
    → Vector (pgvector) ‖ pg_trgm → RRF → Top 15
    → MatchedNewsItem[] (distance 포함)

[6] 병렬 LLM (Claude Sonnet) — 2개 동시 실행 후 final_report
    ├─ generate_swot_list(resume, company, job_title, chunks, industry)
    │   → {"strengths": [...], "weaknesses": [...], "opportunities": [...], "threats": [...]}
    ├─ generate_relevance_analysis(resume, chunks, company, industry, job_title)
    │   → markdown string
    └─ generate_final_report(resume, company, job_title, industry, swot, news_titles)
        → markdown string (면접 준비 포인트 + 최종 권고사항)

[7] ReportResponse 조립 및 반환
```

#### 에러 응답

| 상태코드 | 조건 | 설명 |
|---|---|---|
| `422` | 파일 없음 | `detail: "자소서 PDF 파일이 필요합니다."` |
| `422` | 텍스트 추출 실패 | `detail: "PDF에서 텍스트를 추출할 수 없습니다."` |
| `413` | 파일 크기 > 5MB | `detail: "파일 크기 초과 (N KB). 최대 5 MB."` |
| `415` | PDF 이외 파일 형식 | `detail: "PDF 파일만 지원합니다."` |

---

## 2. 기타 엔드포인트

### Pipeline C — 자소서 단독 분석

#### POST `/api/v1/resume/analyze`

| 항목 | 내용 |
|---|---|
| Request | PDF 또는 DOCX 파일 (multipart) |
| Response | `ResumeAnalysis` |

```json
{
  "skills": ["Python", "FastAPI"],
  "experience_keywords": ["백엔드 개발 3년"],
  "target_role": "백엔드 개발자",
  "strengths": ["문제 해결력"],
  "search_keywords": ["삼성전자", "반도체"]
}
```

#### POST `/api/v1/resume/parse`

텍스트 추출만 수행 (LLM 호출 없음). `{ "text": "..." }` 반환.

---

### 검색 엔드포인트

#### POST `/api/v1/search`

| 항목 | 내용 |
|---|---|
| Request | `{ "query": "...", "top_k": 10, "version": "v2" }` |
| Response | 청크 리스트 |

---

### 헬스체크

#### GET `/api/v1/health`

```json
{"status": "ok"}
```

---

## 3. 데이터 모델 (Pydantic)

모든 모델은 `app/schemas/data_models.py` 에 정의.

### 프론트 연동 모델 (`/report` 엔드포인트)

```python
class ResumeProfile(BaseModel):
    company: str = ""
    job_title: str = ""
    industry: str = ""
    skills: List[str] = []
    experiences: List[str] = []

class MatchedNewsItem(BaseModel):
    id: int = 0
    title: str = ""
    job_category: str = ""
    published_at: Optional[datetime] = None
    url: str = ""
    distance: float = 0.0   # 0.0 ~ 1.0 (낮을수록 유사)

class SWOTList(BaseModel):           # 지원자 관점 SWOT — List[str] 필드
    strengths: List[str] = []
    weaknesses: List[str] = []
    opportunities: List[str] = []
    threats: List[str] = []

class ReportResponse(BaseModel):
    resume_profile: ResumeProfile
    matched_news: List[MatchedNewsItem] = []
    matched_news_count: int = 0
    relevance_analysis: str = ""
    swot: SWOTList
    final_report: str = ""
```

### 내부 서비스 모델

```python
class SWOT(BaseModel):               # 기업 분석용 — string 필드
    strengths: str = ""
    weaknesses: str = ""
    opportunities: str = ""
    threats: str = ""

class IndustryData(BaseModel):
    industry: str
    trends: List[str]
    keywords: List[Keyword]
    article_count: int

class CompanyAnalysis(BaseModel):
    company: str
    industry: str
    analysis_date: datetime
    swot: SWOT
    interview_qna: List[InterviewQNA]
    article_count: int
    news_sources: List[CompanyNewsArticle]

class ResumeAnalysis(BaseModel):
    skills: List[str] = []
    experience_keywords: List[str] = []
    target_role: Optional[str] = None
    strengths: List[str] = []
    search_keywords: List[str] = []
```

---

## 4. LLM 서비스 메서드 (`app/services/llm_service.py`)

### 프론트 파이프라인용 메서드

| 메서드 | 모델 | 반환 타입 | 설명 |
|---|---|---|---|
| `analyze_resume(text)` | Claude Haiku | `dict` | 자소서 구조화 |
| `transform_query(text)` | Claude Haiku | `dict` | 검색 쿼리 최적화 |
| `generate_swot_list(resume, company, job_title, chunks, industry)` | Claude Sonnet | `Dict[str, List[str]]` | 지원자 관점 SWOT |
| `generate_relevance_analysis(resume, chunks, company, industry, job_title)` | Claude Sonnet | `str` (markdown) | 역량-트렌드 연관성 분석 |
| `generate_final_report(resume, company, job_title, industry, swot, news_titles)` | Claude Sonnet | `str` (markdown) | 면접 준비 종합 리포트 |

### 내부 서비스 메서드

| 메서드 | 설명 |
|---|---|
| `extract_trends(articles, industry)` | 산업 트렌드 3문장 추출 |
| `extract_keywords(articles)` | 키워드 리스트 추출 |
| `generate_swot_analysis(company, articles)` | 기업 SWOT (string 필드) |
| `generate_interview_questions(company, resume, articles)` | 면접 Q&A 생성 |
| `stream_industry_trends(articles, industry)` | SSE 스트리밍 |
| `stream_swot(company, articles)` | SSE 스트리밍 |

---

## 5. CORS 설정

```env
# .env
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

---

## 6. 성능 목표

| 단계 | 목표 |
|---|---|
| 전체 `/report` 응답 | < 30초 |
| PDF 파싱 + 자소서 분석 | < 5초 |
| 하이브리드 검색 | < 3초 |
| 병렬 LLM 분석 (2개 동시) | < 20초 |
