# Test Report (Snapshot)

## 기준일

- 2026-02-16

## 현황

- 테스트 코드는 `tests/api`, `tests/unit`, `tests/integration`에 존재
- 현재 환경에서는 `pytest` 실행 바이너리 부재로 실실행 검증은 미수행
- API 엔드포인트 테스트(`tests/api/test_api_endpoints.py`)를 추가하여
  `/api/v1/health`, `/api/v1/analysis/industry`, `/api/v1/analysis/company`를 검증 가능 상태로 구성

## 실행 방법

```bash
python3 -m pip install -e ".[dev,test]"
python3 -m pytest -v
```

## 리스크

- 외부 API 호출은 mock 기반 테스트가 주이며, 실제 키 기반 E2E는 별도 검증 필요
- LLM 응답 품질(정확도/지연시간)은 자동화 지표 테스트가 아직 부족
