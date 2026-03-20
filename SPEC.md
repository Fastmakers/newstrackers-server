# NewStrackers Server — 명세서 인덱스

모든 명세서는 `docs/` 디렉터리에 있습니다.

| 파일 | 내용 |
|---|---|
| `docs/00_system_architecture.md` | 전체 시스템 구조, AI 에이전트 코딩 규칙, 파일 위치 |
| `docs/01_infra_env_spec.md` | 환경 변수, DB 연결, 인프라 설정 |
| `docs/02_search_pipeline_spec.md` | 하이브리드 검색 (V1/V2/V3), RRF, pgvector, pg_trgm |
| `docs/03_api_spec.md` | 전체 API 엔드포인트 명세 (프론트 연동 + Job 시스템 포함) |
| `docs/04_benchmark_spec.md` | 검색 성능 벤치마크 실험 |
| `docs/05_report_jobs_spec.md` | 비동기 Job 시스템 — DB 구조, Worker, 엔드포인트 명세 |
| `docs/ASYNC_JOB_SYSTEM.md` | Job 시스템 구현 기록 (2026-03-12 완료) — 프론트엔드 연동 포함 |
| `docs/ARCHITECTURE.md` | 서비스 계층 리팩토링 기록 (Tier 1/2/3, DI 체인) |
| `docs/PIPELINE.md` | 오프라인 뉴스 데이터 처리 파이프라인 (Phase 1~5) |

---

**새 작업 시 시작점:** `docs/00_system_architecture.md`
