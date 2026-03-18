# 07_progressive_stream_spec.md — 단계별 결과 스트리밍

> **목적**: 각 파이프라인 단계가 완료되는 즉시 결과를 프론트엔드에 스트리밍해,
> 사용자가 전체 완료를 기다리지 않고 단계별로 결과를 확인할 수 있게 한다.
> 최종 리포트는 Claude 토큰 단위 스트리밍으로 타이핑 효과를 준다.

---

## 1. 현재 vs 목표

| 항목 | 현재 | 목표 |
|---|---|---|
| 진행 표시 | progress 이벤트만 (% 숫자) | progress + partial 결과 즉시 렌더링 |
| 뉴스 기사 | 전체 완료 후 표시 | step 4 완료 즉시 카드 등장 |
| SWOT / 산업 분석 | 전체 완료 후 표시 | step 5 완료 즉시 컴포넌트 등장 |
| 최종 리포트 | 전체 완료 후 표시 | Claude 토큰 단위 타이핑 효과 |
| 결과 저장 | Job 워커가 DB 저장 | 스트림 완료 후 동일하게 DB 저장 |

---

## 2. SSE 이벤트 설계

### 기존 이벤트 (유지)

```
data: {"type": "progress", "step": N, "status": "start"|"done", "label": "...", "detail": "..."}
data: {"type": "result",   "data": {...ReportResponse...}}
data: {"type": "error",    "message": "..."}
```

### 신규 이벤트

```
data: {"type": "partial", "field": "resume_profile",    "data": {...ResumeProfile...}}
data: {"type": "partial", "field": "matched_news",      "data": [...], "count": 15}
data: {"type": "partial", "field": "swot",              "data": {...SWOTList...}}
data: {"type": "partial", "field": "relevance_analysis","data": "### 산업 트렌드 요약\n..."}
data: {"type": "token",   "field": "final_report",      "token": "## 면접"}
```

> **하위 호환**: 워커(`worker.py`)는 `partial` / `token` 이벤트를 무시한다 (현재 코드에서 이미 처리 안 함).

### 전체 이벤트 순서

```
progress(2, start) + progress(3, start)
    ↓ [Haiku 병렬: analyze_resume + transform_query]
progress(2, done) + progress(3, done)
partial(resume_profile)                     ← 자소서 분석 결과 즉시 표시

progress(4, start)
    ↓ [hybrid_search]
progress(4, done)
partial(matched_news)                       ← 뉴스 카드 즉시 표시

progress(5, start)
    ↓ [Sonnet 병렬: generate_swot_list + generate_relevance_analysis]
progress(5, done)
partial(swot)                               ← SWOT 즉시 표시
partial(relevance_analysis)                 ← 산업 분석 즉시 표시

progress(6, start)
    ↓ [Sonnet streaming: stream_final_report]
token(final_report, "## 면접")
token(final_report, " 준비")
... (N개)
progress(6, done)

result({...ReportResponse 전체...})         ← 마지막 완성 snapshot
```

---

## 3. 신규 엔드포인트

### POST `/api/v1/analysis/stream`

기존 Job 폴링 방식과 병행 운영. 신규 분석 요청 시 이 엔드포인트를 사용.

**Request** (multipart/form-data) — `POST /api/v1/jobs`와 동일

| 필드 | 타입 | 필수 |
|---|---|---|
| `file` | File (PDF) | ✅ |
| `company` | string | 선택 |
| `job_title` | string | 선택 |
| `industry` | string | 선택 |
| `career_level` | `"신입"` \| `"경력"` | 선택 (기본: `"신입"`) |

**Response** `200 text/event-stream`

위 섹션 2의 이벤트 순서대로 SSE 스트리밍.
마지막 `result` 이벤트에 `job_id`, `report_id` 포함:

```json
{
  "type": "result",
  "job_id": "550e8400-...",
  "report_id": "661f9500-...",
  "data": { ...ReportResponse... }
}
```

스트림 완료 시 DB에 Job(`completed`) + Report 저장.

**Header:** `Authorization: Bearer <token>` (선택 — 있으면 `user_id` 연결)

---

## 4. 변경 파일 목록

### Backend

| 파일 | 변경 내용 |
|---|---|
| `app/services/report_generator.py` | `stream_final_report()` 메서드 추가 |
| `app/services/report_pipeline.py` | `stream()` — `partial` 이벤트 + `token` 이벤트 추가 |
| `app/api/v1/endpoints/analysis.py` | 신규 파일 — `POST /analysis/stream` 엔드포인트 |
| `app/api/v1/router.py` | analysis 라우터 등록 |

### Frontend

| 파일 | 변경 내용 |
|---|---|
| `src/api.ts` | `streamAnalysis()` 함수 추가 (fetch + ReadableStream) |
| `src/components/UploadSection.tsx` | 스트리밍 흐름으로 교체, 단계별 렌더링 |
| `src/components/StreamingReport.tsx` | 신규 — 스트리밍 전용 레이아웃 컴포넌트 |

> **Note**: `EventSource`는 GET만 지원. POST SSE는 `fetch` + `ReadableStream`으로 처리.

---

## 5. 구현 Phase

### Phase 1 — Backend: `stream_final_report()` + pipeline `partial` 이벤트
**변경 파일**: `report_generator.py`, `report_pipeline.py`

- `ReportGenerator.stream_final_report()`: `stream_text()` 래핑, 동일 프롬프트 사용
- `ReportPipeline.stream()`: 각 step 완료 후 `partial` 이벤트 yield
- step 6: `generate_final_report` → `stream_final_report`로 교체, `token` 이벤트 yield

**테스트**: `tests/unit/test_pipeline_partial_events.py`
- pipeline mock → 이벤트 타입 순서 검증
- `partial` 이벤트 data 구조 검증
- `token` 이벤트 누적 시 `final_report` 복원 검증

---

### Phase 2 — Backend: `/analysis/stream` 엔드포인트
**변경 파일**: `app/api/v1/endpoints/analysis.py` (신규), `router.py`

- PDF 파싱 → `ReportPipeline.stream()` → SSE 응답
- 스트림 완료 시 Job + Report DB 저장 (`job_id`, `report_id` result 이벤트에 포함)
- 인증 선택적 (`get_optional_user_id`)

**테스트**: `tests/integration/test_analysis_stream_endpoint.py`
- 정상 흐름: 이벤트 순서 + DB 저장 확인
- 에러 흐름: pipeline 오류 시 `error` 이벤트 반환

---

### Phase 3 — Frontend: 단계별 렌더링
**변경 파일**: `api.ts`, `UploadSection.tsx`, `StreamingReport.tsx` (신규)

- `streamAnalysis()`: `fetch` + `ReadableStream` SSE 파서
- `UploadSection`: 제출 → 스트리밍 모드 전환
- `partial` 이벤트마다 해당 컴포넌트 마운트
- `token` 이벤트마다 `final_report` 텍스트 누적 → 타이핑 효과

**렌더링 순서**:
```
[자소서 프로필 카드] ← partial(resume_profile)
[뉴스 기사 카드]     ← partial(matched_news)
[SWOT]              ← partial(swot)
[산업 분석]          ← partial(relevance_analysis)
[최종 리포트 타이핑] ← token(final_report) x N
```

**테스트**: 수동 E2E — 각 컴포넌트 순서대로 등장 확인

---

## 6. 워커 하위 호환

`worker.py`의 `_process_job()`은 `stream()` 결과를 소비하지만
`partial` / `token` 이벤트는 `_STEP_PROGRESS` 딕셔너리에 없으므로 자동으로 무시됨.
코드 변경 불필요.

```python
# worker.py — 기존 코드 그대로 동작
pct = _STEP_PROGRESS.get((step, status))  # partial/token → pct=None → skip
```

---

## 7. 구현 시작 조건

- [ ] Phase 1 테스트 통과 → commit
- [ ] Phase 2 테스트 통과 → commit
- [ ] Phase 3 수동 확인 → commit
