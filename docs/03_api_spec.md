# 03_api_spec.md — API 엔드포인트 명세

> **Single Source of Truth for all API endpoints.**
> 프론트엔드 연동 엔드포인트 / 내부 서비스 엔드포인트 / 데이터 모델 전체 포함.

---

## 1. 프론트엔드 연동 엔드포인트

프론트엔드가 실제로 호출하는 엔드포인트는 **두 개**입니다 (배치 / SSE 스트리밍).

### POST `/api/v1/analysis/report/stream` ← 프론트엔드 기본 호출 (SSE)

SSE(Server-Sent Events) 스트리밍으로 진행 단계를 실시간 전송하고 최종 결과를 반환합니다.

이벤트 형식:
```
data: {"type": "progress", "step": 1, "status": "start"|"done", "label": "...", "detail": "..."}
data: {"type": "result", "data": {...ReportResponse...}}
data: {"type": "error", "message": "..."}
```

Request / Response 구조는 `/report`와 동일합니다.

---

### POST `/api/v1/analysis/report`

자소서 PDF를 업로드하면 산업 뉴스 기반 종합 취업 전략 리포트를 반환합니다.

#### Request (multipart/form-data)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | File (PDF) | ✅ | 자소서 PDF 파일 (최대 5 MB) |
| `industry` | string | 선택 | 희망 산업군 (예: `반도체`, `AI 인공지능`) |
| `company` | string | 선택 | 목표 기업 (예: `삼성전자`) |
| `job_title` | string | 선택 | 희망 직무 (예: `백엔드 개발자`) |
| `career_level` | string | 선택 | `"신입"` \| `"경력"` (기본값: `"신입"`) |
| `include_raw_news` | string | 선택 | `"true"` 고정 (프론트 하드코딩, 서버에서 무시) |
| `report_mode` | string | 선택 | `"fast"` 고정 (프론트 하드코딩, 서버에서 무시) |

> `company`, `job_title`, `industry` 가 Form에 없으면 자소서 분석 결과에서 자동 추론합니다.
> `career_level` 은 모든 LLM 프롬프트에 반영됩니다:
> - `"신입"` → 성장 가능성·학습 의지·잠재력 기준, 실무 경험 부재를 고려한 평가
> - `"경력"` → 즉시 전력·전문성·성과 기준, 이직 동기와 경력 활용도 중심 평가

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
    "weaknesses": ["약점 1", "약점 2"],
    "opportunities": ["기회 1", "기회 2"],
    "threats": ["위협 1", "위협 2"]
  },
  "final_report": "## 면접 준비 포인트\n...\n## 최종 권고사항\n..."
}
```

> **SWOT 방향**: 지원자(자소서 작성자) 관점 SWOT — 해당 기업에 지원했을 때의 강점/약점/기회/위협.
> 기업 자체의 SWOT 분석이 아닙니다.
>
> **`distance` 필드 해석**: 하이브리드 검색(V2) 결과에서 벡터 매칭 아이템만 `distance > 0` 값을 가짐.
> 키워드 전용 매칭 아이템은 `distance=0.0`. 프론트엔드는 `distance=0.0` 을 "키워드 매칭" 배지로 표시.
>
> **유사도 표시**: `(1 - distance) * 100` 절대 수치. 특정 산업/기업 관련 기사가 적은 경우 낮은 수치가 그대로 보여야 판단 가능.
> 벡터 매칭 없거나 평균 유사도 < 70% (distance > 0.3) 이면 낮은 관련성 경고 배너 표시.

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

[5] 하이브리드 검색 (V2)
    hybrid_search(query, keyword_query, top_k=15)
    → 벡터(pgvector cosine) ‖ 키워드(pg_trgm) 병렬 실행 → RRF(k=60) 융합 → Top 15
    → MatchedNewsItem[] (distance: 벡터 코사인 거리, 키워드 전용은 0.0)
    ※ Cross-Encoder 리랭킹(V3)은 ENABLE_RERANKER=true 시 활성화 (현재 기본 비활성)

[6] 병렬 LLM (Claude Sonnet) — swot ‖ relevance 동시 실행 → final_report
    ├─ generate_swot_list(resume, company, job_title, chunks, industry)
    │   → {"strengths": [...], "weaknesses": [...], "opportunities": [...], "threats": [...]}
    │   출력 형식: 각 항목에 완전한 서술형 문장 2~3개 (키워드 나열 금지)
    │   예: "지원자는 3년간 FastAPI로 대규모 백엔드 시스템을 구축해 온 경험이 있어,
    │        삼성전자 DX부문의 MSA 전환 전략에 즉시 기여할 수 있습니다."
    ├─ generate_relevance_analysis(resume, chunks, company, industry, job_title)
    │   → markdown string — 반드시 아래 고정 템플릿 구조 출력:
    │
    │   ### 산업 트렌드 요약
    │   - [뉴스 근거 트렌드 1 — 1~2문장]
    │   - [뉴스 근거 트렌드 2 — 1~2문장]
    │   - [뉴스 근거 트렌드 3 — 1~2문장]
    │
    │   ### 역량-트렌드 연결 포인트
    │   - **[지원자 역량명]** — [트렌드와 어떻게 연결되는지 1~2문장]
    │   - **[지원자 역량명]** — [트렌드와 어떻게 연결되는지 1~2문장]
    │   - **[지원자 역량명]** — [트렌드와 어떻게 연결되는지 1~2문장]
    │
    │   ### 면접 활용 키워드
    │   - **[키워드 1]**: [면접에서 활용하는 방법 1문장]
    │   - **[키워드 2]**: [면접에서 활용하는 방법 1문장]
    │   - **[키워드 3]**: [면접에서 활용하는 방법 1문장]
    │
    │   규칙: 각 섹션 정확히 3개 불릿 / 섹션 외 서문·결론 금지 / ### 헤딩 문자열 정확히 유지
    └─ generate_final_report(resume, company, job_title, industry, swot, relevance_analysis)
        → markdown string — 반드시 아래 고정 템플릿 구조 출력:

        ## 면접 준비 포인트

        ### Q1. [예상 질문 — 뉴스 트렌드 연관]
        [질문 배경 1문장]
        **핵심 답변 방향:** [2~3문장]

        ### Q2. [예상 질문 — 지원자 경험 연관]
        [질문 배경 1문장]
        **핵심 답변 방향:** [2~3문장]

        ### Q3. [예상 질문 — 직무 적합성 연관]
        [질문 배경 1문장]
        **핵심 답변 방향:** [2~3문장]

        ---

        ## 최종 권고사항

        ### 핵심 준비 사항
        1. **[항목명]** — [실행 방법 1~2문장]
        2. **[항목명]** — [실행 방법 1~2문장]
        3. **[항목명]** — [실행 방법 1~2문장]

        ### 차별화 전략
        [지원자만의 차별점 2~3문장]

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

## 2. 비동기 Job 시스템 엔드포인트

분석 결과를 DB에 영속 저장하고, 탭을 닫아도 분석이 계속되는 Job 큐 방식.
상세 명세: `docs/05_report_jobs_spec.md`

### POST `/api/v1/jobs` — Job 생성

PDF 업로드 + 파라미터를 받아 즉시 `job_id`를 반환. 실제 분석은 워커가 백그라운드로 처리.

**Request** (multipart/form-data)

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file` | File (PDF) | ✅ | 자소서 PDF (최대 5 MB) |
| `company` | string | 선택 | 목표 기업 |
| `job_title` | string | 선택 | 희망 직무 |
| `industry` | string | 선택 | 희망 산업군 |
| `career_level` | string | 선택 | `"신입"` \| `"경력"` (기본: `"신입"`) |

**Response** `202 Accepted`
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "분석 요청이 접수되었습니다. GET /jobs/{job_id} 로 진행상황을 확인하세요."
}
```

---

### GET `/api/v1/jobs` — 내 Job 목록

**Header:** `Authorization: Bearer <token>` (없으면 빈 배열 반환)

```json
{
  "jobs": [
    {
      "job_id": "...",
      "status": "completed",
      "current_step": 6,
      "step_label": "리포트 생성 완료",
      "progress_pct": 100,
      "company": "삼성전자",
      "job_title": "백엔드 개발자",
      "industry": "반도체",
      "created_at": "2026-03-12T10:00:00Z",
      "completed_at": "2026-03-12T10:01:20Z",
      "report_id": "..."
    }
  ]
}
```

---

### GET `/api/v1/jobs/{job_id}` — Job 상태 조회

단건 조회. 프론트에서 1.5~3초 간격으로 폴링 가능.
`status=completed`이면 `report_id` 포함, `status=failed`이면 `error_msg` 포함.

---

### GET `/api/v1/jobs/{job_id}/stream` — SSE 진행상황 (재접속 가능)

기존 `/report/stream`과 이벤트 형식 동일. `progress_pct` 필드가 추가됨.
DB를 1.5초마다 폴링. 재접속 시 현재 상태부터 이어서 수신.

```
data: {"type": "progress", "step": 4, "status": "done", "label": "뉴스 검색 완료", "detail": "15건 매칭", "progress_pct": 55}
data: {"type": "result", "data": {...ReportResponse...}}
data: {"type": "error", "message": "..."}
```

---

### GET `/api/v1/jobs/reports` — 내 리포트 목록

**Header:** `Authorization: Bearer <token>`

```json
{
  "reports": [
    {
      "report_id": "...",
      "job_id": "...",
      "company": "삼성전자",
      "job_title": "백엔드 개발자",
      "matched_news_count": 15,
      "created_at": "2026-03-12T10:01:20Z"
    }
  ]
}
```

---

### GET `/api/v1/jobs/reports/{report_id}` — 리포트 상세

기존 `/report` 응답과 동일한 `ReportResponse` 필드 + `report_id`, `job_id`, `created_at`.

---

## 3. 기타 엔드포인트

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

## 4. 데이터 모델 (Pydantic)

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
    distance: float = 0.0   # 벡터 코사인 거리 0.0~1.0 (낮을수록 유사)
                             # distance=0.0 → 키워드 매칭 전용 (벡터 거리 없음)

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

## 5. LLM 서비스 메서드 (`app/services/llm_service.py`)

### 프론트 파이프라인용 메서드

| 메서드 | 모델 | 반환 타입 | 설명 |
|---|---|---|---|
| `analyze_resume(text)` | Claude Haiku | `dict` | 자소서 구조화 |
| `transform_query(text)` | Claude Haiku | `dict` | 검색 쿼리 최적화 |
| `generate_swot_list(resume, company, job_title, chunks, industry, career_level)` | Claude Sonnet | `Dict[str, List[str]]` | 지원자 관점 SWOT — career_level 반영 |
| `generate_relevance_analysis(resume, chunks, company, industry, job_title, career_level)` | Claude Sonnet | `str` (markdown) | 역량-트렌드 연관성 분석 — career_level 반영 |
| `generate_final_report(resume, company, job_title, industry, swot, relevance_analysis, career_level)` | Claude Sonnet | `str` (markdown) | 고정 템플릿 면접 준비 리포트 — career_level 반영 |

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

## 6. CORS 설정

```env
# .env
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

---

## 7. 성능 목표

| 단계 | 목표 |
|---|---|
| 전체 `/report` 응답 | < 30초 |
| PDF 파싱 + 자소서 분석 | < 5초 |
| 하이브리드 검색 | < 3초 |
| 병렬 LLM 분석 (2개 동시) | < 20초 |
