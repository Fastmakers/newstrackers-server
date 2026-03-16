# 05_report_jobs_spec.md — 비동기 Job 시스템 명세

> **목적**: 사용자가 분석 중 탭을 닫거나 새로고침해도 분석 결과·진행 상태를 잃지 않도록
> Job 큐 + Worker 패턴으로 구현한다.
>
> **구현 완료 기준**: `ASYNC_JOB_SYSTEM.md` 참고 (2026-03-12)

---

## 1. 기존 방식 vs 신규 방식 비교

| 항목             | 기존 (`/report/stream`)   | 신규 (`/jobs`)                    |
| ---------------- | ------------------------- | --------------------------------- |
| 분석 결과 저장   | ❌ 메모리 — 탭 닫으면 소실 | ✅ DB 영속 저장                    |
| 진행 상태 복구   | ❌ 불가                    | ✅ 재접속 시 현재 상태부터 수신    |
| 분석 이력 조회   | ❌ 불가                    | ✅ 사용자별 과거 리포트 목록       |
| 실시간 진행 표시 | ✅ SSE                     | ✅ 폴링 기반 (1.5~3초 간격, 재접속 가능) |

기존 `/report` / `/report/stream`은 **비로그인 단발성 사용**을 위해 그대로 유지한다.

---

## 2. DB 테이블 (2개)

기존 PostgreSQL에 2개 테이블 추가. Alembic 마이그레이션 `004_add_jobs_reports`.

### 2-1. `analysis_jobs` — Job 메타데이터 + 진행 상태

```sql
CREATE TABLE analysis_jobs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID,                                   -- JWT sub claim (nullable, 비로그인 허용)
    status        TEXT        NOT NULL DEFAULT 'pending', -- 아래 상태값 참고
    company       TEXT,
    job_title     TEXT,
    industry      TEXT,
    career_level  TEXT        NOT NULL DEFAULT '신입',
    resume_text   TEXT,                                   -- PDF 파싱 완료된 원문 (최대 5MB 분량)
    current_step  INTEGER,                                -- 현재 파이프라인 단계 (2~6)
    step_label    TEXT,                                   -- 단계 표시 문자열 (예: "뉴스 검색 완료")
    step_detail   TEXT,                                   -- 부가 메시지 (예: "15건 매칭")
    progress_pct  INTEGER,                                -- 진행률 0~100
    error_msg     TEXT,                                   -- 실패 시 에러 메시지
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,                            -- 워커가 처리 시작한 시각
    completed_at  TIMESTAMPTZ                             -- 완료 또는 실패 시각
);

CREATE INDEX idx_analysis_jobs_user_id  ON analysis_jobs(user_id);
CREATE INDEX idx_analysis_jobs_status   ON analysis_jobs(status);
CREATE INDEX idx_analysis_jobs_created  ON analysis_jobs(user_id, created_at DESC);
```

**status 전이:**

```text
pending ──► running ──► completed
                   └──► failed
```

| 상태        | 의미                                        |
| ----------- | ------------------------------------------- |
| `pending`   | Job 생성됨, 워커 픽업 대기 중               |
| `running`   | 워커가 분석 진행 중                         |
| `completed` | 분석 완료, `analysis_reports`에 결과 저장됨 |
| `failed`    | 분석 실패, `error_msg` 설정됨               |

**진행률 매핑:**

| pipeline step | 이벤트           | progress_pct |
| ------------- | ---------------- | ------------ |
| step=2, done  | 이력서 분석 완료 | 25%          |
| step=3, done  | 쿼리 최적화 완료 | 30%          |
| step=4, done  | 뉴스 검색 완료   | 55%          |
| step=5, done  | SWOT/분석 완료   | 80%          |
| step=6, done  | 리포트 생성 완료 | 100%         |

---

### 2-2. `analysis_reports` — 완료 결과

```sql
CREATE TABLE analysis_reports (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id              UUID UNIQUE NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    user_id             UUID,                  -- 조회 편의를 위해 복사
    resume_profile      JSONB,                 -- ResumeProfile
    matched_news        JSONB,                 -- MatchedNewsItem[]
    matched_news_count  INTEGER,
    relevance_analysis  TEXT,                  -- markdown
    swot                JSONB,                 -- SWOTList
    final_report        TEXT,                  -- markdown
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> **users FK 미설정**: users 테이블 스키마 확정 후 `005` 마이그레이션으로 추가 예정.

---

## 3. API 엔드포인트

모든 경로 앞에 `/api/v1` 프리픽스 붙음.
구현 파일: `app/api/v1/endpoints/jobs.py`

### POST `/api/v1/jobs` — Job 생성

PDF 파싱 → Job DB 삽입 → `job_id` 즉시 반환 (분석은 워커가 처리).

**Request** (multipart/form-data)

| 필드           | 타입       | 필수 | 설명                                  |
| -------------- | ---------- | ---- | ------------------------------------- |
| `file`         | File (PDF) | ✅    | 자소서 PDF (최대 5 MB)                |
| `company`      | string     | 선택 | 목표 기업                             |
| `job_title`    | string     | 선택 | 희망 직무                             |
| `industry`     | string     | 선택 | 희망 산업군                           |
| `career_level` | string     | 선택 | `"신입"` \| `"경력"` (기본: `"신입"`) |

**Response** `202 Accepted`

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "분석 요청이 접수되었습니다. GET /api/v1/jobs/{job_id} 로 진행상황을 확인하세요."
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
      "step_detail": "",
      "progress_pct": 100,
      "company": "삼성전자",
      "job_title": "소프트웨어 엔지니어",
      "industry": "전자",
      "created_at": "2026-03-12T10:00:00Z",
      "started_at": "2026-03-12T10:00:03Z",
      "completed_at": "2026-03-12T10:01:20Z",
      "error_msg": null,
      "report_id": "..."
    }
  ]
}
```

---

### GET `/api/v1/jobs/{job_id}` — Job 상태 단건 조회

프론트에서 1.5~3초 간격으로 폴링 가능. 위 Jobs 배열의 단일 객체와 동일한 구조.


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
      "job_title": "소프트웨어 엔지니어",
      "industry": "전자",
      "matched_news_count": 15,
      "created_at": "2026-03-12T10:01:20Z"
    }
  ]
}
```

---

### GET `/api/v1/jobs/reports/{report_id}` — 리포트 상세

기존 `/report` 응답(`ReportResponse`)과 동일한 필드 + `report_id`, `job_id`, `created_at`.

```json
{
  "report_id": "...",
  "job_id": "...",
  "resume_profile": { "company": "...", "job_title": "...", "skills": [], "experiences": [] },
  "matched_news": [...],
  "matched_news_count": 15,
  "relevance_analysis": "### 산업 트렌드 요약\n...",
  "swot": { "strengths": [], "weaknesses": [], "opportunities": [], "threats": [] },
  "final_report": "## 면접 준비 포인트\n...",
  "created_at": "2026-03-12T10:01:20Z"
}
```

---

## 4. Worker 아키텍처

**파일:** `app/services/worker.py`

- FastAPI `lifespan`에서 `asyncio.create_task`로 백그라운드 루프 실행
- **3초마다** DB 폴링해 `status=pending` Job을 최대 5개 가져옴
- 각 Job을 `asyncio.create_task`로 병렬 처리 (동시 상한: `_MAX_CONCURRENT=3`)
- 중복 실행 방지: 폴링 즉시 `pending → running` 상태 변경

```
loop (3초 간격):
  SELECT id FROM analysis_jobs WHERE status='pending' LIMIT 5
  → UPDATE status='running', started_at=now()
  → asyncio.create_task(run_job(job))

run_job(job):
  ReportPipeline.stream() 실행
  각 progress 이벤트마다 → UPDATE current_step, step_label, progress_pct
  완료 → INSERT analysis_reports + UPDATE status='completed', completed_at=now()
  실패 → UPDATE status='failed', error_msg=...
```

---

## 5. 인증

**관련 파일:**
- `app/core/security.py` — `create_access_token`, `verify_access_token`
- `app/core/auth.py` — `get_optional_user_id` (Optional auth 의존성)
- `app/core/dependencies.py` — `get_current_user` (필수 auth, 401 반환)
- `app/api/v1/endpoints/auth.py` — `/auth/register`, `/auth/login`, `/auth/me`

`.env` 설정:

```env
SECRET_KEY=안전한_랜덤_시크릿키
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_DAYS=30
```

| 의존성                 | 토큰 없을 때 |
| ---------------------- | ------------ |
| `get_current_user`     | HTTP 401     |
| `get_optional_user_id` | `None` 반환  |

- `POST /jobs`: 비로그인 허용 (`user_id=NULL`로 저장)
- `GET /jobs`, `GET /jobs/reports`: 토큰 없으면 빈 배열 반환

---

## 6. 구현 파일 맵

```text
app/
├── core/
│   ├── auth.py              # get_optional_user_id
│   ├── security.py          # JWT 생성/검증
│   └── dependencies.py      # get_worker()
├── db/
│   ├── models.py            # AnalysisJobDB, AnalysisReportDB
│   └── repositories/
│       └── job_repository.py  # Job/Report CRUD
├── schemas/
│   └── job_models.py        # JobCreateResponse, JobStatus, JobSummary
├── services/
│   └── worker.py            # AnalysisWorker (asyncio polling)
└── api/v1/
    ├── router.py            # /jobs 라우터 등록
    └── endpoints/
        └── jobs.py          # 전체 Jobs/Reports 엔드포인트
alembic/versions/
└── 004_add_jobs_reports.py  # analysis_jobs, analysis_reports 테이블
```

---

## 7. Pydantic 스키마 (`app/schemas/job_models.py`)

```python
class JobCreateResponse(BaseModel):
    job_id: UUID
    status: str       # "pending"
    message: str

class JobStatus(BaseModel):
    job_id: UUID
    status: str       # pending | running | completed | failed
    current_step: Optional[int]
    step_label: Optional[str]
    step_detail: Optional[str]
    progress_pct: Optional[int]
    company: Optional[str]
    job_title: Optional[str]
    industry: Optional[str]
    career_level: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_msg: Optional[str]
    report_id: Optional[UUID]

class JobSummary(BaseModel):
    """목록 조회용 — result(대용량) 제외"""
    job_id: UUID
    status: str
    company: Optional[str]
    job_title: Optional[str]
    created_at: datetime
```

---

## 8. 마이그레이션 실행

```bash
cd newstrackers-server
alembic upgrade head   # 001 → 002 → 003(users) → 004(jobs/reports) 순서
```

---

## 9. 알려진 제약 / TODO

- **users FK 미설정**: users 테이블 확정 후 `005` 마이그레이션으로 FK 제약 추가
- **Job 만료 정책**: 오래된 job/report 자동 삭제 미구현 (주기적 cleanup 필요)
- **재시도 로직**: 실패한 job 자동 재시도 미구현
- **동시 처리 상한**: `_MAX_CONCURRENT=3` 하드코딩 — 설정값으로 이동 가능
- **DELETE 엔드포인트**: 리포트 삭제 미구현 (CORS에 DELETE 메서드 추가 필요)
- **서버 재시작 복구**: 재시작 시 `running` 상태 job을 `pending`으로 리셋하는 startup 훅 미구현
