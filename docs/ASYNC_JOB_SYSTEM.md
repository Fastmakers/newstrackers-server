# 비동기 분석 Job 시스템 명세서

> 작성일: 2026-03-12
> 관련 마이그레이션: 004_add_jobs_reports, 005_refactor_jobs_reports, 006, 007

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
   │         [Worker가 3초마다 polling]                   │
   │                          │── SELECT pending jobs ──▶│
   │                          │◀── job ─────────────────│
   │                          │── UPDATE status=running ▶│
   │                          │                          │
   │                          │  (pipeline.run_with_progress() 실행)
   │                          │── UPDATE progress_pct ───▶│ (partial_result 누적)
   │                          │── UPDATE progress_pct ───▶│
   │                          │── INSERT analysis_reports ▶│
   │                          │── UPDATE status=completed ▶│
   │                          │                          │
   │── GET /jobs/{id} ───────▶│── SELECT job ────────────▶│
   │◀── { status, progress,  │                          │
   │     partial_result }     │                          │
   │                          │                          │
   │── GET /reports/{id} ────▶│── SELECT report ──────────▶│
   │◀── { 분석 결과 전체 } ───│                          │
```

> 프론트는 1.5~3초 간격으로 `GET /jobs/{id}` 를 폴링해 `progress_pct`와 `partial_result`를 수신한다.
> `status=completed`가 되면 `report_id`로 리포트 상세를 조회한다.

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
| `progress_pct` | INT | 진행률 0~100 |
| `retry_count` | INT | 워커 재시도 횟수 (기본 0) |
| `partial_result` | JSONB | 단계별 완료 결과 (폴링용 점진적 렌더링, 기본 `{}`) |
| `report_id` | UUID FK | 완료 후 analysis_reports.id 참조 (nullable) |
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

> FK 방향 주의: `analysis_jobs.report_id` → `analysis_reports.id` (reports 테이블에 job_id 컬럼 없음)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 리포트 식별자 |
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
> users 테이블이 확정되면 추후 migration으로 FK를 추가한다.

---

## 4. Worker 동작 방식

**파일:** `app/services/worker.py`

- FastAPI `lifespan`에서 `asyncio.create_task`로 백그라운드 루프 실행
- **3초마다** DB를 폴링해 `status=pending` job을 최대 3개 가져옴 (`_MAX_CONCURRENT=3`)
- 각 job을 `asyncio.create_task`로 병렬 처리 (동시 상한: 3개)
- 중복 실행 방지: `pending → running` 상태 변경을 폴링 단계에서 먼저 수행

**진행률 매핑** (ReportPipeline.run_with_progress() on_step 콜백 → progress_pct):

| on_step 호출 | pct | partial_result에 추가되는 키 |
|---|---|---|
| step=1 | 20% | `resume_profile` |
| step=3 | 50% | `matched_news` |
| step=4 | 80% | `swot`, `relevance_analysis` |
| step=5 | 100% | `final_report` |

> `partial_result`는 단계마다 머지(누적)되므로 step=5 완료 시점에 전체 결과가 모두 포함된다.

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
      "progress_pct": 100,
      "retry_count": 0,
      "company": "삼성전자",
      "job_title": "소프트웨어 엔지니어",
      "industry": "전자",
      "career_level": "신입",
      "created_at": "2026-03-12T10:00:00Z",
      "started_at": "2026-03-12T10:00:03Z",
      "completed_at": "2026-03-12T10:01:20Z",
      "error_msg": null,
      "report_id": "...",
      "partial_result": {}
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

