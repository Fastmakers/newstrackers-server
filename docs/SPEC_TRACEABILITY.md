# SPEC Traceability Matrix

이 문서는 `SPEC.md` 요구사항과 구현/테스트를 연결하는 실행 가능한 체크리스트입니다.

## 사용 방법

1. `SPEC.md`의 기능 요구를 작은 단위(`REQ-xxx`)로 쪼갭니다.
2. 각 요구사항에 구현 파일, API 계약, 테스트를 연결합니다.
3. 상태(`planned`, `in_progress`, `implemented`, `verified`)를 갱신합니다.
4. CI에서 최소 1개 이상의 테스트 ID가 없는 `implemented` 항목은 실패 처리합니다.

## 상태 정의

- `planned`: 요구사항 정의만 완료
- `in_progress`: 구현 진행 중
- `implemented`: 코드 반영 완료
- `verified`: 테스트로 검증 완료

## Matrix

| Req ID | 요구사항 | 구현 위치 | API 계약 | 테스트 | 상태 |
|---|---|---|---|---|---|
| REQ-IND-001 | 산업 트렌드 분석 요청 처리 | `app/analysis/industry_analyzer.py` | `POST /api/v1/analysis/industry` | `tests/api/test_api_endpoints.py::test_industry_analysis_endpoint` | implemented |
| REQ-IND-002 | 산업 키워드 분류(tech/corp/policy) | `app/services/llm_service.py` | `POST /api/v1/analysis/industry` | `tests/unit/test_analysis.py::test_keyword_type_validation` | implemented |
| REQ-IND-003 | 월별 감정 분석 결과 생성 | `app/analysis/industry_analyzer.py` | `POST /api/v1/analysis/industry` | `tests/unit/test_analysis.py::test_monthly_sentiment_analysis` | implemented |
| REQ-CMP-001 | 기업 분석 요청 처리 | `app/analysis/company_analyzer.py` | `POST /api/v1/analysis/company` | `tests/api/test_api_endpoints.py::test_company_analysis_endpoint` | implemented |
| REQ-CMP-002 | 5대 지표 점수 산출 | `app/analysis/company_analyzer.py` | `POST /api/v1/analysis/company` | `tests/unit/test_analysis.py::test_five_dimension_scoring` | implemented |
| REQ-CMP-003 | SWOT 생성 | `app/services/llm_service.py` | `POST /api/v1/analysis/company` | `tests/integration/test_pipeline.py::test_company_analysis_workflow` | in_progress |
| REQ-OPS-001 | API 상태 확인 endpoint 제공 | `app/api/v1/endpoints/health.py` | `GET /api/v1/health` | `tests/api/test_api_endpoints.py::test_v1_health` | implemented |
| REQ-DATA-001 | 뉴스 캐시 TTL 만료 처리 | `app/services/news_service.py` | N/A | `tests/unit/test_news_service.py::test_cache_set_and_get` | in_progress |

## 다음 보강 우선순위

1. `verified` 상태로 올리기 위한 실제 테스트 실행 파이프라인 구축
2. `REQ-CMP-003`, `REQ-DATA-001` 보강 테스트 추가
3. `SPEC.md`의 수치형 목표(SLA, 정확도)에 대한 측정 테스트 추가
