# 05_report_jobs_spec.md — 분석 Job 관리 & 진행 상태 영속화

> **목적**: 사용자가 분석 중 탭을 닫거나 새로고침해도 분석 결과/진행 상태를 잃지 않도록
> Job 큐 + Worker 패턴으로 전환한다.
> 로그인/로그아웃(UUID 기반 userId)과 연동되어 사용자별 분석 이력을 관리한다.

---

## 1. 기존 방식 vs 신규 방식 비교

| 항목 | 기존 (SSE in-memory) | 신규 (Job Queue + Worker) |
|------|----------------------|--------------------------|
| 분석 결과 저장 | ❌ 메모리만 — 탭 닫으면 소실 | ✅ DB 영속 저장 |
| 진행 상태 복구 | ❌ 불가 | ✅ 재접속 시 이벤트 이어받기 |
| 분석 이력 조회 | ❌ 불가 | ✅ 사용자별 과거 리포트 목록 |
| 실시간 진행 표시 | ✅ SSE | ✅ SSE (DB poll 기반, 재접속 가능) |
| 서버 장애 복구 | ❌ 분석 처음부터 다시 | ✅ pending 상태 재시작 가능 |

---

## 2. 추가 DB 테이블 (2개)

기존 PostgreSQL에 2개 테이블을 추가한다. 별도 DB 인스턴스 불필요.

### 2-1. `report_jobs` — 잡 메타데이터 + 최종 결과

```sql
CREATE TABLE report_jobs (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID        NOT NULL,                    -- users.id (FK, auth 팀 구현)
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 아래 상태값 참고
    company      VARCHAR(200),
    job_title    VARCHAR(200),
    industry     VARCHAR(200),
    career_level VARCHAR(10) NOT NULL DEFAULT '신입',
    pdf_data     BYTEA,                                   -- 업로드된 PDF 원본 (최대 5MB)
    result       JSONB,                                   -- ReportResponse JSON (done 시 설정)
    error_message TEXT,                                   -- 실패 메시지 (failed 시 설정)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 인덱스
CREATE INDEX idx_report_jobs_user_id   ON report_jobs(user_id);
CREATE INDEX idx_report_jobs_status    ON report_jobs(status);
CREATE INDEX idx_report_jobs_created   ON report_jobs(user_id, created_at DESC);
```

**상태값 (status) 전이:**

```
pending ──► processing ──► done
                       └──► failed
```

| 상태 | 의미 |
|------|------|
| `pending` | 잡 생성됨, 워커 픽업 대기 중 |
| `processing` | 워커가 분석 진행 중 |
| `done` | 분석 완료, `result` 컬럼에 JSON 저장됨 |
| `failed` | 분석 실패, `error_message` 설정됨 |

---

### 2-2. `report_job_events` — 단계별 진행 이벤트

워커가 각 파이프라인 단계 시작/완료 시 행을 삽입한다.
SSE 엔드포인트는 이 테이블을 폴링해 클라이언트에 전달한다.

```sql
CREATE TABLE report_job_events (
    id         BIGSERIAL    PRIMARY KEY,
    job_id     UUID         NOT NULL REFERENCES report_jobs(id) ON DELETE CASCADE,
    step       SMALLINT     NOT NULL,          -- 1~6
    status     VARCHAR(10)  NOT NULL,          -- 'start' | 'done'
    label      VARCHAR(200) NOT NULL,
    detail     VARCHAR(500),                   -- 선택적 부가 설명 (예: "15건 매칭")
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- SSE 폴링 쿼리 최적화
CREATE INDEX idx_job_events_job_id ON report_job_events(job_id, id);
```

---

## 3. 신규 엔드포인트

### 3-1. `POST /api/v1/jobs` — 잡 생성 + PDF 업로드

분석 시작 요청. PDF를 DB에 저장하고 즉시 `job_id`를 반환한다.
실제 분석은 백그라운드 워커가 비동기로 처리한다.

**Request** (multipart/form-data)

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file` | File (PDF) | ✅ | 자소서 PDF (최대 5 MB) |
| `company` | string | 선택 | 목표 기업 |
| `job_title` | string | 선택 | 희망 직무 |
| `industry` | string | 선택 | 희망 산업군 |
| `career_level` | string | 선택 | `"신입"` \| `"경력"` (기본: `"신입"`) |

**Request Header**

| 헤더 | 설명 |
|------|------|
| `X-User-ID: <uuid>` | 사용자 UUID (auth 팀 발급) |

**Response** `201 Created`

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "created_at": "2026-03-11T10:00:00Z"
}
```

---

### 3-2. `GET /api/v1/jobs/{job_id}/stream` — SSE 진행 스트림 (재접속 가능)

실시간 진행 상황을 SSE로 스트리밍한다.
**재접속 시 기존에 발생한 이벤트를 모두 먼저 전송하고(catch-up), 이후 새 이벤트를 실시간으로 전달한다.**

**이벤트 형식:**

```
data: {"type": "progress", "step": 1, "status": "start", "label": "PDF 파싱 중...", "detail": ""}
data: {"type": "progress", "step": 1, "status": "done",  "label": "PDF 파싱 완료",  "detail": "3,412자 추출"}
...
data: {"type": "result", "data": {...ReportResponse...}}
data: {"type": "error",  "message": "PDF에서 텍스트를 추출할 수 없습니다."}
```

**동작 흐름:**

```
클라이언트 접속
      │
      ▼
report_job_events WHERE job_id = ? ORDER BY id ASC
      │
      ├─ 기존 이벤트 있으면 → 즉시 전송 (catch-up)
      │
      ├─ job.status = 'done'   → result 이벤트 전송 → 연결 종료
      ├─ job.status = 'failed' → error 이벤트 전송 → 연결 종료
      │
      └─ job.status = 'processing' 또는 'pending'
             │
             └─ 0.5초 간격 폴링 → 새 이벤트 전송 → 완료/실패 시 종료
```

**Query parameter:**
- `?last_event_id=<bigint>` — 선택. 마지막으로 받은 이벤트 ID 이후부터만 전송 (재접속 최적화)

---

### 3-3. `GET /api/v1/jobs/{job_id}` — 잡 상태/결과 조회

```json
{
  "job_id": "550e8400-...",
  "status": "done",
  "company": "삼성전자",
  "job_title": "백엔드 개발자",
  "industry": "반도체",
  "career_level": "신입",
  "created_at": "2026-03-11T10:00:00Z",
  "updated_at": "2026-03-11T10:02:30Z",
  "result": { ...ReportResponse... },   // status=done 이면 포함
  "error_message": null                 // status=failed 이면 메시지
}
```

---

### 3-4. `GET /api/v1/jobs` — 사용자 잡 목록

Header `X-User-ID` 기준으로 조회. `result`(대용량 JSONB)는 제외한 메타데이터만 반환.

```json
[
  {
    "job_id": "550e8400-...",
    "status": "done",
    "company": "삼성전자",
    "job_title": "백엔드 개발자",
    "created_at": "2026-03-11T10:00:00Z"
  }
]
```

---

## 4. Worker 아키텍처

### 4-1. 선택: PostgreSQL-based polling (Redis 불필요)

기존 인프라(PostgreSQL만)로 구현 가능한 방식. Redis 추가 없이 운영 가능.

```
┌──────────────────────────────────────────────────────┐
│  FastAPI (uvicorn)                                    │
│  POST /jobs → DB insert(pending) → return job_id     │
│  GET  /jobs/{id}/stream → poll report_job_events     │
└──────────────────────────────────────────────────────┘
                         │
              report_jobs (status=pending)
                         │
┌──────────────────────────────────────────────────────┐
│  Worker Process (별도 프로세스 or asyncio task)       │
│                                                       │
│  loop:                                                │
│    SELECT ... FROM report_jobs                        │
│    WHERE status='pending'                             │
│    ORDER BY created_at LIMIT 1                        │
│    FOR UPDATE SKIP LOCKED   ← 동시 실행 안전         │
│                                                       │
│    → UPDATE status='processing'                       │
│    → ReportPipeline.run(inp, event_callback)          │
│       event_callback: INSERT INTO report_job_events  │
│    → UPDATE status='done', result=JSON               │
│       or UPDATE status='failed', error_message=...   │
│                                                       │
│    sleep(1초)                                         │
└──────────────────────────────────────────────────────┘
```

**Worker 실행 방법 (2가지 중 선택):**

| 방법 | 장점 | 단점 |
|------|------|------|
| **FastAPI startup 이벤트**에서 asyncio 백그라운드 태스크로 실행 | 단일 프로세스, 배포 간단 | 서버 재시작 시 처리 중단 |
| **별도 Worker 프로세스** (`python -m app.worker`) | 서버와 독립, 스케일 아웃 가능 | 배포 설정 추가 필요 |

> 권장: 초기엔 FastAPI 내장 백그라운드 태스크로 시작, 트래픽 증가 시 별도 프로세스로 전환.

---

### 4-2. ReportPipeline 수정 사항

`pipeline.stream()` → `pipeline.run_with_callback(inp, on_event)` 형태 추가:

```python
def run_with_callback(
    self,
    inp: ReportInput,
    on_event: Callable[[int, str, str, str], None],  # (step, status, label, detail)
) -> ReportResponse:
    """Worker용 동기 실행 — 각 단계마다 on_event 콜백 호출."""
    on_event(1, "start", "PDF 파싱 중...", "")
    # ... 분석 ...
    on_event(1, "done", "PDF 파싱 완료", f"{len(resume_text):,}자 추출")
    # ...
    return result
```

---

## 5. 프론트엔드 연동 변경 사항

### 5-1. 분석 시작 흐름

```
기존: POST /report/stream → SSE 연결 유지하며 분석
신규: POST /jobs → job_id 즉시 수신 → GET /jobs/{id}/stream → SSE 재접속 가능
```

### 5-2. 탭 닫기 / 새로고침 복구

```
1. 탭 닫힘 → job_id를 localStorage에 저장 (X-User-ID와 함께)
2. 재접속 → GET /jobs 로 in-progress/pending 잡 확인
3. GET /jobs/{job_id}/stream 재접속 → catch-up 이벤트로 현재 단계 표시
```

### 5-3. 사용자 이력 화면 (신규)

- 과거 분석 리포트 목록 표시 (`GET /jobs`)
- 완료된 분석 클릭 → 결과 재조회 (`GET /jobs/{job_id}`)

---

## 6. 엔드포인트 전체 목록 (업데이트)

| 엔드포인트 | 방식 | Auth | 설명 |
|------------|------|------|------|
| `POST /api/v1/analysis/report/stream` | SSE | ❌ | **기존 유지** — 비로그인 단발성 사용 |
| `POST /api/v1/analysis/report` | JSON | ❌ | **기존 유지** — 배치 |
| `POST /api/v1/jobs` | JSON | ✅ | **신규** — 잡 생성 |
| `GET /api/v1/jobs` | JSON | ✅ | **신규** — 사용자 잡 목록 |
| `GET /api/v1/jobs/{job_id}` | JSON | ✅ | **신규** — 잡 상태/결과 |
| `GET /api/v1/jobs/{job_id}/stream` | SSE | ✅ | **신규** — 재접속 가능 진행 스트림 |

> 기존 `/report` / `/report/stream` 엔드포인트는 **비로그인 단발성 사용**을 위해 유지한다.
> 로그인 사용자는 `/jobs` 엔드포인트를 통해 이력 관리가 가능하다.

---

## 7. 데이터 모델 추가 (Pydantic)

```python
# app/schemas/job_models.py (신규)

class JobCreateResponse(BaseModel):
    job_id: UUID
    status: str       # "pending"
    created_at: datetime

class JobStatus(BaseModel):
    job_id: UUID
    status: str       # pending | processing | done | failed
    company: str
    job_title: str
    industry: str
    career_level: str
    created_at: datetime
    updated_at: datetime
    result: Optional[ReportResponse] = None
    error_message: Optional[str] = None

class JobSummary(BaseModel):
    """목록 조회용 — result(대용량) 제외"""
    job_id: UUID
    status: str
    company: str
    job_title: str
    created_at: datetime
```

---

## 8. 구현 우선순위

| 단계 | 작업 | 의존성 |
|------|------|--------|
| **Phase 1** | `report_jobs` / `report_job_events` 테이블 Alembic 마이그레이션 | — |
| **Phase 2** | `JobRepository` — CRUD + `FOR UPDATE SKIP LOCKED` 쿼리 | Phase 1 |
| **Phase 3** | `ReportPipeline.run_with_callback()` 추가 | — |
| **Phase 4** | Worker 루프 구현 (`app/worker/report_worker.py`) | Phase 2, 3 |
| **Phase 5** | `/jobs` 엔드포인트 4개 구현 | Phase 2, 4 |
| **Phase 6** | `GET /jobs/{id}/stream` SSE (catch-up + poll) | Phase 2, 4 |
| **Phase 7** | 프론트엔드 — job_id 저장, 재접속, 이력 목록 UI | Phase 5, 6 |
| **Phase 8** | auth 팀 `X-User-ID` 헤더 연동 | auth 팀 완료 후 |

---

## 9. 주의사항

- `pdf_data BYTEA` 저장은 DB 용량을 소비함. 장기적으로 S3로 이전 고려.
- Worker 폴링 간격 1초는 DB 부하가 낮으나, 다수 동시 요청 시 증가 고려.
- `FOR UPDATE SKIP LOCKED`는 PostgreSQL 9.5+ 필수 (AWS RDS 해당).
- `result JSONB`는 `ReportResponse.model_dump(mode='json')`으로 직렬화.
- Worker가 processing 중 서버 재시작 → 해당 잡은 `processing` 상태로 영구 대기.
  복구: 서버 시작 시 `processing` 상태 잡을 `pending`으로 리셋하는 startup 훅 필요.
