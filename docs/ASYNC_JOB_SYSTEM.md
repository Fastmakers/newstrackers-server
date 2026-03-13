# 비동기 분석 Job 시스템 명세서

> 작성일: 2026-03-12
> 관련 커밋: 003_add_jobs_reports migration

---

## 1. 왜 만들었나

기존 `/api/v1/analysis/report/stream` 엔드포인트는 SSE로 분석 진행상황을 보여주지만,
**사용자가 페이지를 이탈하면 분석이 중단**되고 결과도 사라지는 문제가 있었다.

이 시스템은 다음 두 가지를 해결한다:
1. 분석을 **서버 워커가 백그라운드에서 완료**시켜 결과를 DB에 저장
2. 사용자가 **나갔다 돌아와도** 진행상황과 완료 결과를 조회할 수 있음

---

## 2. 전체 흐름

```
[사용자]                    [서버]                      [DB]
   │                          │                          │
   │── POST /jobs ──────────▶│                          │
   │   (PDF + 파라미터)        │── INSERT analysis_jobs ─▶│ (status=pending)
   │◀── { job_id } ──────────│                          │
   │                          │                          │
   │── GET /jobs/{id}/stream ▶│                          │
   │   (SSE 연결)              │                          │
   │                          │                          │
   │         [Worker가 3초마다 polling]                   │
   │                          │── SELECT pending jobs ──▶│
   │                          │◀── job ─────────────────│
   │                          │── UPDATE status=running ▶│
   │                          │                          │
   │                          │  (pipeline.stream() 실행) │
   │◀── progress events ─────│── UPDATE progress ───────▶│
   │◀── progress events ─────│── UPDATE progress ───────▶│
   │◀── result event ────────│── INSERT analysis_reports ▶│
   │                          │── UPDATE status=completed ▶│
   │                          │                          │
   │ (나갔다가 돌아온 경우)      │                          │
   │── GET /jobs/{id} ───────▶│── SELECT job ────────────▶│
   │◀── { status, progress } │                          │
   │── GET /reports/{id} ────▶│── SELECT report ──────────▶│
   │◀── { 분석 결과 } ────────│                          │
```

---

## 3. DB 테이블 구조

### `analysis_jobs` — Job 스케줄

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | job 식별자 |
| `user_id` | UUID nullable | 로그인 사용자의 UUID (users.id 참조, FK 미설정) |
| `status` | TEXT | `pending` / `running` / `completed` / `failed` |
| `company` | TEXT | 지원 기업명 |
| `job_title` | TEXT | 지원 직무 |
| `industry` | TEXT | 산업군 |
| `career_level` | TEXT | `신입` / `경력` |
| `resume_text` | TEXT | PDF에서 파싱한 이력서 원문 |
| `current_step` | INT | 현재 단계 번호 (2~6) |
| `step_label` | TEXT | 단계 표시 문자열 (예: "뉴스 검색 완료") |
| `step_detail` | TEXT | 상세 메시지 (예: "15건 매칭") |
| `progress_pct` | INT | 진행률 0~100 |
| `created_at` | TIMESTAMPTZ | job 생성 시각 |
| `started_at` | TIMESTAMPTZ | 워커가 처리 시작한 시각 |
| `completed_at` | TIMESTAMPTZ | 완료 또는 실패 시각 |
| `error_msg` | TEXT | 실패 시 에러 메시지 |

**status 전이:**
```
pending ──▶ running ──▶ completed
                  └──▶ failed
```

### `analysis_reports` — 완료 결과

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 리포트 식별자 |
| `job_id` | UUID FK (unique) | analysis_jobs.id 참조 |
| `user_id` | UUID nullable | 조회 편의를 위해 복사 |
| `resume_profile` | JSONB | ResumeProfile (company, job_title, skills[], experiences[]) |
| `matched_news` | JSONB | MatchedNewsItem[] |
| `matched_news_count` | INT | 매칭 뉴스 건수 |
| `relevance_analysis` | TEXT | 산업 관련성 분석 (markdown) |
| `swot` | JSONB | SWOTList (strengths[], weaknesses[], opportunities[], threats[]) |
| `final_report` | TEXT | 최종 면접 리포트 (markdown) |
| `created_at` | TIMESTAMPTZ | 저장 시각 |

> **왜 users FK가 없나?**
> users 테이블은 별도 팀이 관리한다. FK 제약 없이 UUID만 저장하고,
> users 테이블이 확정되면 004 마이그레이션으로 FK를 추가한다.

---

## 4. Worker 동작 방식

**파일:** `app/services/worker.py`

- FastAPI `lifespan`에서 `asyncio.create_task`로 백그라운드 루프 실행
- **3초마다** DB를 폴링해 `status=pending` job을 최대 5개 가져옴
- 각 job을 `asyncio.create_task`로 병렬 처리 (동시 상한: 3개)
- 중복 실행 방지: `pending → running` 상태 변경을 폴링 단계에서 먼저 수행

**진행률 매핑** (ReportPipeline.stream() 이벤트 → progress_pct):

| pipeline step | 이벤트 | 의미 | progress_pct |
|---|---|---|---|
| step=2, done | 이력서 분석 완료 | Haiku 이력서 파싱 | 25% |
| step=3, done | 쿼리 최적화 완료 | Haiku 검색어 변환 | 30% |
| step=4, done | 뉴스 검색 완료 | Hybrid Search | 55% |
| step=5, done | SWOT/분석 완료 | Sonnet 병렬 분석 | 80% |
| step=6, done | 리포트 생성 완료 | Sonnet 최종 리포트 | 100% |

> step=2,3은 pipeline 내부에서 병렬 실행되어 거의 동시에 done된다.

### 실험용 timing metrics

이번 구조에서는 DB 스키마를 바꾸지 않고 아래 값을 계산한다.

| 메트릭 | 계산식 | 의미 |
|---|---|---|
| `age_ms` | `now - created_at` | 현재까지 job이 살아있는 시간 |
| `queue_wait_ms` | `started_at - created_at` | queue에서 대기한 시간 |
| `processing_time_ms` | `(completed_at or now) - started_at` | worker가 실제 처리한 시간 |
| `total_lead_time_ms` | `(completed_at or now) - created_at` | 요청 접수부터 현재/완료까지 총 시간 |

이 값들은 두 경로에서 동시에 확인할 수 있다.

1. `GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`, `GET /api/v1/jobs/reports*`
2. worker 로그 (`dispatched`, `completed`, `failure_metrics`)

따라서 실험 시 다음 비교가 가능하다.

- API 내장 worker 모드와 분리 worker 모드의 `queue_wait_ms` 차이
- 동일 부하에서 `processing_time_ms` 안정성 차이
- 최종 사용자 체감 지표인 `total_lead_time_ms` 차이

---

## 5. API 엔드포인트

모든 엔드포인트는 `/api/v1/jobs` 에 마운트된다.

### `POST /api/v1/jobs` — Job 생성

**역할:** PDF 파싱 → Job DB 삽입 → job_id 즉시 반환 (분석은 워커가 처리)

**요청:** `multipart/form-data`
```
file        UploadFile  자소서 PDF (필수, 최대 5MB)
company     str         지원 기업 (선택)
job_title   str         지원 직무 (선택)
industry    str         산업군 (선택)
career_level str        "신입" | "경력" (기본: "신입")
```

**응답:** HTTP 202
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "분석 요청이 접수되었습니다. GET /jobs/{job_id} 로 진행상황을 확인하세요."
}
```

---

### `GET /api/v1/jobs` — 내 Job 목록

**역할:** 로그인한 사용자의 전체 job 목록 반환 (최신순)

**헤더:** `Authorization: Bearer <token>` (없으면 빈 배열 반환)

**응답:**
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

### `GET /api/v1/jobs/{job_id}` — Job 상태 조회 (폴링용)

**역할:** 특정 job의 현재 상태 단건 조회. 프론트에서 1.5~3초 간격으로 폴링해 사용 가능.

**응답:** 위 jobs 배열의 단일 객체와 동일한 구조.

- `status=completed` 이면 `report_id` 가 채워져 있음
- `status=failed` 이면 `error_msg` 에 원인이 있음

---

### `GET /api/v1/jobs/{job_id}/stream` — SSE 진행상황 구독

**역할:** SSE로 실시간 진행상황 수신. **기존 `/report/stream`과 이벤트 형식 동일**하므로
프론트의 SSE 파서를 재사용할 수 있다.

**특징:**
- DB를 1.5초마다 폴링해 `progress_pct` 변화 감지 시 이벤트 발송
- **재접속 지원:** 사용자가 나갔다가 돌아와도 연결하면 현재 상태부터 이어서 수신
- job이 이미 `completed`이면 즉시 result 이벤트를 발송하고 스트림 종료

**이벤트 형식:**
```
data: {"type": "progress", "step": 4, "status": "done", "label": "뉴스 검색 완료", "detail": "15건 매칭", "progress_pct": 55}

data: {"type": "result", "data": { ...ReportResponse... }}

data: {"type": "error", "message": "..."}
```

> `progress_pct` 필드가 기존 `/report/stream` 이벤트에 추가된 유일한 차이점이다.

---

### `GET /api/v1/jobs/reports` — 내 리포트 목록

**역할:** 완료된 리포트 목록 (요약 정보). 히스토리 화면용.

**헤더:** `Authorization: Bearer <token>`

**응답:**
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

### `GET /api/v1/jobs/reports/{report_id}` — 리포트 상세

**역할:** 분석 결과 전체 조회. 기존 `/report` 응답과 동일한 필드 구조.

**응답:**
```json
{
  "report_id": "...",
  "job_id": "...",
  "resume_profile": { "company": "...", "job_title": "...", "skills": [], "experiences": [] },
  "matched_news": [ ... ],
  "matched_news_count": 15,
  "relevance_analysis": "### 산업 트렌드 요약\n...",
  "swot": { "strengths": [], "weaknesses": [], "opportunities": [], "threats": [] },
  "final_report": "## 면접 준비 포인트\n...",
  "created_at": "2026-03-12T10:01:20Z"
}
```

---

## 6. 인증 연동 방법

**관련 파일:**
- `app/core/security.py` — `create_access_token`, `verify_access_token`, `hash_password`
- `app/core/auth.py` — `get_optional_user_id` (Optional auth 의존성)
- `app/core/dependencies.py` — `get_current_user` (필수 auth 의존성, 401 반환)
- `app/api/v1/endpoints/auth.py` — `/auth/register`, `/auth/login`, `/auth/me`

`.env` 설정:
```env
SECRET_KEY=안전한_랜덤_시크릿키_여기에_입력
ALGORITHM=HS256            # 기본값
ACCESS_TOKEN_EXPIRE_DAYS=30  # 기본값
```

- 토큰의 **`sub` claim** = user_id (UUID 문자열)
- `GET /jobs`, `GET /jobs/reports` 는 user_id 없으면 빈 배열 반환
- `POST /jobs` 는 비로그인도 가능 (user_id=NULL로 저장)
- 필수 인증 엔드포인트 추가 시: `Depends(get_current_user)` 사용

**인증 의존성 두 종류:**

| 의존성 | 위치 | 토큰 없을 때 |
|---|---|---|
| `get_current_user` | `dependencies.py` | HTTP 401 반환 |
| `get_optional_user_id` | `auth.py` | None 반환 |

---

## 7. 파일 구조

```
app/
├── core/
│   ├── auth.py              # JWT → user_id 의존성 (NEW)
│   ├── config.py            # JWT_SECRET, JWT_ALGORITHM 추가 (MODIFIED)
│   └── dependencies.py      # get_worker() 추가 (MODIFIED)
├── db/
│   ├── models.py            # AnalysisJobDB, AnalysisReportDB 추가 (MODIFIED)
│   └── repositories/
│       └── job_repository.py  # Job/Report CRUD (NEW)
├── schemas/
│   └── job_models.py        # Job/Report API 스키마 (NEW)
├── services/
│   └── worker.py            # AnalysisWorker — DB polling 워커 (NEW)
└── api/v1/
    ├── router.py            # /jobs 라우터 추가 (MODIFIED)
    └── endpoints/
        └── jobs.py          # 전체 Jobs/Reports 엔드포인트 (NEW)
alembic/versions/
└── 003_add_jobs_reports.py  # analysis_jobs, analysis_reports 테이블 (NEW)
```

---

## 8. 마이그레이션 실행

```bash
cd newstrackers-server
alembic upgrade head   # 001 → 002 → 003(users) → 004(jobs/reports) 순서로 실행
```

또는 단계별:
```bash
alembic upgrade 003   # users 테이블만
alembic upgrade 004   # jobs/reports 테이블 추가
```

---

## 9. 기존 `/report/stream` 과의 관계

기존 엔드포인트는 **그대로 유지**된다.
새 Job 시스템은 병렬 운영되며, 로그인 사용자는 결과 저장이 필요할 때 `/jobs`를 사용하고
빠른 일회성 분석은 기존 `/report/stream`을 계속 쓸 수 있다.

| | 기존 `/report/stream` | 새 `/jobs` |
|---|---|---|
| 결과 저장 | ❌ | ✅ |
| 재접속 지원 | ❌ | ✅ |
| 히스토리 조회 | ❌ | ✅ |
| 응답 지연 | 즉시 스트리밍 | job_id 즉시 반환, 분석은 비동기 |
| 로그인 필요 | ❌ | ❌ (Optional) |

---

## 10. 프론트엔드 연동 (JobHistory 컴포넌트)

**파일:** `newstrackers-frontend/src/components/JobHistory.tsx`

### 탭 구조 (2026-03-12 개편)

| 탭 | 내용 |
|---|---|
| 자소서 업로드 | 업로드 폼 → 분석 완료 시 결과 인라인 표시 → "← 새 분석" 으로 폼 복귀 |
| 분석 기록 | Job 목록 → "결과 보기" 클릭 시 리포트 인라인 표시 → "← 분석 기록" 으로 목록 복귀 |

- "분석 결과" 탭 제거 — 업로드 결과는 업로드 탭 내에서, 기록 결과는 기록 탭 내에서 표시
- 각 분석이 독립적인 뷰로 동작

### 자동 새로고침

- **주기:** 5초마다 `GET /api/v1/jobs` 자동 폴링
- **동작:** 초기 로드는 로딩 스피너 표시, 이후 자동 새로고침은 silent (스피너 없음)
- **중단 조건:** 리포트 상세 뷰로 진입 시 폴링 중단, 목록으로 돌아오면 재시작

### 버그 수정 (2026-03-12)

`GET /api/v1/jobs` 응답에서 completed 상태 job의 `report_id`가 항상 `null`로 반환되던 문제 수정.
- **원인:** `AnalysisJobDB.report` 관계가 `lazy="noload"` → `_job_to_response`에서 `job.report` 항상 `None`
- **수정:** `list_jobs` 엔드포인트에서 completed job마다 `repo.get_report_by_job()`으로 명시 조회

---

## 11. 알려진 제약 / TODO

- **users FK:** users 테이블 스키마가 확정되면 004 마이그레이션으로 FK 제약 추가
- **job 만료 정책:** 오래된 job/report 자동 삭제 로직 미구현 (주기적 cleanup 필요)
- **재시도 로직:** 실패한 job 자동 재시도 미구현
- **동시 처리 상한:** 현재 `_MAX_CONCURRENT=3` 하드코딩. 설정값으로 이동 가능
- **DELETE 엔드포인트:** 리포트 삭제 미구현 (CORS에 DELETE 메서드 추가 필요)
