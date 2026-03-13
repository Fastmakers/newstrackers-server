# Async Worker Experiment Guide

이 문서는 다음 두 구조를 같은 입력으로 비교하기 위한 실행 절차를 설명한다.

1. `api+worker` 통합 모드
2. `api-only + worker-only` 분리 모드

비교 대상은 구조뿐이고, queue(DB), pipeline, 입력 PDF, 요청 수는 동일하게 유지한다.

---

## 1. 실험 목적

확인하려는 질문은 세 가지다.

1. worker를 FastAPI 프로세스 안에 둘 때 API 요청 응답성이 더 나빠지는가
2. worker를 분리하면 queue 대기시간(`queue_wait_ms`)이 실제로 줄어드는가
3. 사용자가 체감하는 총 완료시간(`total_lead_time_ms`)은 어느 쪽이 더 좋은가

---

## 2. 준비

### 공통 환경

- 같은 DB 사용
- 같은 `.env` 사용
- 같은 PDF 사용
- 같은 요청 수와 제출 동시성 사용
- 가능하면 같은 머신, 같은 시간대에 연속 실행

### 입력 파일

다음 중 하나처럼 실제 PDF를 사용한다.

```bash
resume_kimjinju.pdf
resume_kimjinju_bank.pdf
```

---

## 3. 실행 모드 A: API + Worker 통합

```bash
RUN_WORKER_IN_API=true uvicorn app.main:app --host 0.0.0.0 --port 8000
```

별도 worker 프로세스는 띄우지 않는다.

로드 테스트:

```bash
python scripts/benchmark_async_jobs.py \
  --base-url http://127.0.0.1:8000 \
  --pdf resume_kimjinju.pdf \
  --jobs 12 \
  --submit-concurrency 4 \
  --poll-interval-sec 1.5 \
  --label inprocess \
  --save
```

---

## 4. 실행 모드 B: API / Worker 분리

API:

```bash
RUN_WORKER_IN_API=false uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Worker:

```bash
python -m app.worker_main
```

로드 테스트:

```bash
python scripts/benchmark_async_jobs.py \
  --base-url http://127.0.0.1:8000 \
  --pdf resume_kimjinju.pdf \
  --jobs 12 \
  --submit-concurrency 4 \
  --poll-interval-sec 1.5 \
  --label split \
  --save
```

---

## 5. 스크립트가 측정하는 값

### HTTP 레벨

- `submit_request_ms`
  - `POST /api/v1/jobs` 요청 지연시간
- `poll_request_ms`
  - `GET /api/v1/jobs/{job_id}` 폴링 요청 지연시간

### Job 레벨

- `queue_wait_ms`
  - job 생성부터 worker 시작까지 시간
- `processing_time_ms`
  - worker가 실제 분석에 사용한 시간
- `total_lead_time_ms`
  - job 생성부터 완료까지 총 시간

### 실험 레벨

- `wall_clock_sec`
  - 실험 전체 종료까지 걸린 시간
- `throughput_jobs_per_min`
  - 분당 완료 job 수
- `status_counts`
  - `completed`, `failed`, `timeout`, `submit_failed` 건수

---

## 6. 결과 해석

### API 보호 관점

다음 값이 낮아지면 분리 worker의 장점이 있다고 볼 수 있다.

- `submit_request_ms` p95
- `poll_request_ms` p95

이 값들은 API가 백그라운드 분석 영향에서 얼마나 자유로운지 보여준다.

### Worker 처리 관점

다음 값을 비교한다.

- `queue_wait_ms` p50 / p95
- `processing_time_ms` p50 / p95

해석 기준:

- `queue_wait_ms`가 낮아지면 job pickup이 빨라진 것
- `processing_time_ms`가 비슷하면 분리해도 분석 자체 성능은 유지된 것
- `processing_time_ms`가 커지면 CPU/메모리 경쟁이나 외부 의존성 병목을 의심

### 사용자 체감 관점

가장 중요한 값은 `total_lead_time_ms`다.

해석 기준:

- 이 값이 더 낮으면 사용자는 더 빨리 결과를 받는다
- API latency만 좋아지고 `total_lead_time_ms`가 나빠지면, 사용자 경험 전체는 개선되지 않은 것

---

## 7. 추천 실험 순서

1. 소규모
```bash
--jobs 6 --submit-concurrency 2
```

2. 혼합 부하
```bash
--jobs 12 --submit-concurrency 4
```

3. 버스트 부하
```bash
--jobs 24 --submit-concurrency 8
```

각 단계에서 통합 모드와 분리 모드를 같은 조건으로 한 번씩 돌린다.

---

## 8. 권장 비교표

실험 결과 JSON 두 개를 저장했다면 아래 항목만 표로 옮기면 된다.

| label | submit p95 | poll p95 | queue_wait p95 | processing p95 | lead_time p95 | throughput |
|---|---:|---:|---:|---:|---:|---:|
| inprocess | ... | ... | ... | ... | ... | ... |
| split | ... | ... | ... | ... | ... | ... |

---

## 9. 주의사항

- 현재 worker는 DB polling 기반이라 replica가 여러 개면 claim 경쟁을 따로 검증해야 한다.
- 외부 LLM/API 변동성이 크면 구조 차이보다 네트워크 변동이 더 크게 보일 수 있다.
- 가장 공정한 1차 실험은 동일한 시간대에 연속 실행하는 것이다.
