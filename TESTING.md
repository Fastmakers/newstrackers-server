# Testing Guide

## 실행 명령

```bash
# 전체 테스트
python3 -m pytest -v

# API 테스트만
python3 -m pytest tests/api -v

# 단위 테스트만
python3 -m pytest tests/unit -v

# 커버리지
python3 -m pytest --cov=app --cov-report=term-missing tests/
```

## 테스트 범위

- `tests/api`: FastAPI 엔드포인트 레벨 검증
- `tests/unit`: 서비스/분석/모델 단위 검증
- `tests/integration`: 모듈 간 흐름 검증

## 주의사항

- 외부 API(뉴스/LLM) 호출 테스트는 대부분 목(mock) 기반입니다.
- 실제 API 키 기반 E2E 검증은 별도 환경에서 수행하세요.

## 명세서

- 인덱스: `SPEC.md` → `docs/` 디렉터리
- API 명세: `docs/03_api_spec.md`
- 비동기 worker 실험 가이드: `docs/ASYNC_WORKER_EXPERIMENT.md`

## 부하 실험

비동기 job 시스템 비교 실험:

```bash
python scripts/benchmark_async_jobs.py \
  --base-url http://127.0.0.1:8000 \
  --pdf resume_kimjinju.pdf \
  --jobs 12 \
  --submit-concurrency 4 \
  --label inprocess \
  --save
```
