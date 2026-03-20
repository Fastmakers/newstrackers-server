# 03_api_spec.md — API 엔드포인트 명세

> **Single Source of Truth for all API endpoints.**
> 현재 라우터에 등록된 엔드포인트만 기재. (`app/api/v1/router.py` 기준)

---

## 현재 활성 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/v1/health` | 헬스체크 |
| `POST` | `/api/v1/auth/register` | 회원가입 |
| `POST` | `/api/v1/auth/login` | 로그인 |
| `GET` | `/api/v1/auth/me` | 내 정보 |
| `POST` | `/api/v1/jobs` | 분석 Job 생성 |
| `GET` | `/api/v1/jobs` | 내 Job 목록 |
| `GET` | `/api/v1/jobs/{job_id}` | Job 상태 단건 조회 |
| `GET` | `/api/v1/jobs/reports` | 내 완료 리포트 목록 |
| `GET` | `/api/v1/jobs/reports/{report_id}` | 리포트 상세 |

---

## 1. 인증 엔드포인트

### POST `/api/v1/auth/register`

**Request (JSON)**
```json
{ "email": "user@example.com", "nickname": "닉네임", "password": "..." }
```

**Response `201`**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": { "email": "user@example.com", "nickname": "닉네임" }
}
```

| 오류 | 조건 |
|---|---|
| `400` | 이미 등록된 이메일 |

---

### POST `/api/v1/auth/login`

**Request (JSON)**
```json
{ "email": "user@example.com", "password": "..." }
```

**Response `200`** — register와 동일 구조

| 오류 | 조건 |
|---|---|
| `401` | 이메일 또는 비밀번호 불일치 |

---

### GET `/api/v1/auth/me`

**Header:** `Authorization: Bearer <token>` (필수)

**Response `200`**
```json
{ "email": "user@example.com", "nickname": "닉네임" }
```

---

## 2. 분석 Job 엔드포인트

프론트엔드가 사용하는 주 흐름:
```
POST /jobs → job_id 획득 → GET /jobs/{job_id} 폴링 → completed 시 GET /jobs/reports/{report_id}
```

분석 로직은 워커(`app/services/worker.py`)가 백그라운드에서 `ReportPipeline`을 실행.
진행상황은 DB의 `progress_pct` 컬럼으로 추적, 프론트는 3초 간격 폴링으로 확인.

---

### POST `/api/v1/jobs` — Job 생성

**Request (multipart/form-data)**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | File (PDF) | ✅ | 자소서 PDF (최대 5 MB) |
| `company` | string | 선택 | 목표 기업 (예: `삼성전자`) |
| `job_title` | string | 선택 | 희망 직무 (예: `백엔드 개발자`) |
| `industry` | string | 선택 | 희망 산업군 (예: `반도체`) |
| `career_level` | string | 선택 | `"신입"` \| `"경력"` (기본: `"신입"`) |

> `company`, `job_title`, `industry` 가 없으면 자소서 분석 결과에서 자동 추론.
> `career_level` 은 모든 LLM 프롬프트에 반영:
> - `"신입"` → 성장 가능성·학습 의지·잠재력 기준
> - `"경력"` → 즉시 전력·전문성·성과·이직 동기 기준

**Response `202 Accepted`**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "분석 요청이 접수되었습니다. GET /jobs/{job_id} 로 진행상황을 확인하세요."
}
```

| 오류 | 조건 |
|---|---|
| `422` | 파일 없음 / 텍스트 추출 실패 |
| `413` | 파일 크기 > 5 MB |
| `415` | PDF 이외 파일 형식 |

---

### GET `/api/v1/jobs` — 내 Job 목록

**Header:** `Authorization: Bearer <token>` (없으면 빈 배열 반환)

**Response `200`**
```json
{
  "jobs": [
    {
      "job_id": "550e8400-...",
      "status": "completed",
      "progress_pct": 100,
      "retry_count": 0,
      "company": "삼성전자",
      "job_title": "백엔드 개발자",
      "industry": "반도체",
      "career_level": "신입",
      "created_at": "2026-03-12T10:00:00Z",
      "started_at": "2026-03-12T10:00:03Z",
      "completed_at": "2026-03-12T10:01:20Z",
      "error_msg": null,
      "report_id": "661f9500-..."
    }
  ]
}
```

`status` 값: `pending` | `running` | `completed` | `failed`

---

### GET `/api/v1/jobs/{job_id}` — Job 상태 단건 조회

프론트 폴링 전용. 3초 간격 권장.

**Response `200`** — Job 목록의 단일 객체와 동일 구조

`status=completed` 이면 `report_id` 포함.
`status=failed` 이면 `error_msg` 포함.

#### 진행률 매핑 (`progress_pct`)

| 단계 | `progress_pct` | 설명 |
|---|---|---|
| job 생성 (pending) | 0 | 워커 대기 중 |
| 워커 픽업 (running 시작) | 10 | PDF 파싱 완료 (job 생성 시 완료됨) |
| 자소서 AI 분석 완료 | 25 | Claude Haiku |
| 검색 쿼리 최적화 완료 | 30 | Claude Haiku |
| 뉴스 하이브리드 검색 완료 | 55 | pgvector + pg_trgm RRF |
| SWOT + 산업 분석 완료 | 80 | Claude Sonnet (병렬) |
| 최종 리포트 생성 완료 | 100 | Claude Sonnet |

| 오류 | 조건 |
|---|---|
| `404` | job_id 존재하지 않음 |

---

### GET `/api/v1/jobs/reports` — 내 완료 리포트 목록

**Header:** `Authorization: Bearer <token>` (없으면 빈 배열 반환)

**Response `200`**
```json
{
  "reports": [
    {
      "report_id": "661f9500-...",
      "job_id": "550e8400-...",
      "company": "삼성전자",
      "job_title": "백엔드 개발자",
      "industry": "반도체",
      "matched_news_count": 15,
      "created_at": "2026-03-12T10:01:20Z"
    }
  ]
}
```

---

### GET `/api/v1/jobs/reports/{report_id}` — 리포트 상세

**Response `200`**
```json
{
  "report_id": "661f9500-...",
  "job_id": "550e8400-...",
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
  "relevance_analysis": "### 산업 트렌드 요약\n...",
  "swot": {
    "strengths": ["강점 서술형 문장"],
    "weaknesses": ["약점 서술형 문장"],
    "opportunities": ["기회 서술형 문장"],
    "threats": ["위협 서술형 문장"]
  },
  "final_report": "## 면접 준비 포인트\n...",
  "created_at": "2026-03-12T10:01:20Z"
}
```

> **`distance` 필드**: 벡터 코사인 거리 0.0~1.0. `distance=0.0` 은 키워드 전용 매칭.
> **SWOT 방향**: 지원자 관점 — 해당 기업에 지원했을 때의 강점/약점/기회/위협. 기업 자체 SWOT 아님.

| 오류 | 조건 |
|---|---|
| `404` | report_id 존재하지 않음 |

---

## 3. 헬스체크

### GET `/api/v1/health`

```json
{"status": "ok"}
```

---

## 4. 데이터 모델 (Pydantic)

### Job / Report 스키마 (`app/schemas/job_models.py`)

```python
class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus          # pending | running | completed | failed
    progress_pct: int = 0
    retry_count: int = 0
    company: Optional[str]
    job_title: Optional[str]
    industry: Optional[str]
    career_level: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_msg: Optional[str]
    report_id: Optional[str]

class ReportSummaryResponse(BaseModel):
    report_id: str
    job_id: str
    company: Optional[str]
    job_title: Optional[str]
    industry: Optional[str]
    matched_news_count: Optional[int]
    created_at: datetime

class ReportDetailResponse(BaseModel):
    report_id: str
    job_id: str
    resume_profile: Optional[dict]
    matched_news: Optional[list]
    matched_news_count: Optional[int]
    relevance_analysis: Optional[str]
    swot: Optional[dict]
    final_report: Optional[str]
    created_at: datetime
```

### 리포트 내용 모델 (`app/schemas/data_models.py`)

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
    distance: float = 0.0    # 벡터 코사인 거리. 0.0 = 키워드 전용 매칭

class SWOTList(BaseModel):   # 지원자 관점 SWOT — List[str] 필드
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

---

## 5. 파이프라인 단계 (워커 내부)

```
[1] PDF 파싱 — job 생성 시점에 완료 (progress_pct: 0→10 on worker pickup)

[2+3] 자소서 분석 + 쿼리 최적화 — 병렬 (Claude Haiku)
    analyze_resume()   → skills, experience_keywords, target_role, strengths
    transform_query()  → 뉴스 검색 최적화 쿼리
    완료 시 progress_pct: 25 → 30

[4] 하이브리드 검색
    hybrid_search(query, keyword_query, top_k=15)
    → 벡터(pgvector cosine) ‖ 키워드(pg_trgm) 병렬 → RRF(k=60) → Top 15
    완료 시 progress_pct: 55
    ※ Cross-Encoder 리랭킹은 ENABLE_RERANKER=true 시 활성화 (기본 비활성)

[5] SWOT + 산업 연관성 분석 — 병렬 (Claude Sonnet)
    generate_swot_list(resume, company, job_title, chunks, industry, career_level)
    generate_relevance_analysis(resume, chunks, company, industry, job_title, career_level)
    완료 시 progress_pct: 80

[6] 최종 리포트 생성 (Claude Sonnet)
    generate_final_report(resume, company, job_title, industry, swot, relevance_analysis, career_level)
    완료 시 progress_pct: 100

[7] DB 저장 — analysis_reports 저장 + job.report_id 연결
```

### LLM 출력 형식

**`generate_relevance_analysis`** — 고정 템플릿 markdown:
```
### 산업 트렌드 요약
- [트렌드 1]
- [트렌드 2]
- [트렌드 3]

### 역량-트렌드 연결 포인트
- **[역량명]** — [연결 설명]
- **[역량명]** — [연결 설명]
- **[역량명]** — [연결 설명]

### 면접 활용 키워드
- **[키워드]**: [활용법]
- **[키워드]**: [활용법]
- **[키워드]**: [활용법]
```
규칙: 각 섹션 정확히 3개 불릿 / 섹션 외 서문·결론 금지 / `###` 헤딩 문자열 정확히 유지

**`generate_final_report`** — 고정 템플릿 markdown:
```
## 면접 준비 포인트

### Q1. [예상 질문]
[배경 1문장]
**핵심 답변 방향:** [2~3문장]

### Q2. [예상 질문]
...

### Q3. [예상 질문]
...

---

## 최종 권고사항

### 핵심 준비 사항
1. **[항목명]** — [실행 방법]
2. **[항목명]** — [실행 방법]
3. **[항목명]** — [실행 방법]

### 차별화 전략
[지원자만의 차별점 2~3문장]
```

---

## 6. CORS 설정

```env
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```

---

## 7. 성능 목표

| 단계 | 목표 |
|---|---|
| 전체 Job 완료 (생성~완료) | < 60초 |
| PDF 파싱 + 자소서 분석 | < 5초 |
| 하이브리드 검색 | < 3초 |
| 병렬 LLM 분석 (SWOT + 연관성) | < 20초 |
| 최종 리포트 생성 | < 15초 |
