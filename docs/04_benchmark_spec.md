# 04_benchmark_spec.md — 검색 파이프라인 성능 벤치마크 명세

> **목적:** 각 최적화 단계의 효과를 정량적으로 측정하여 "체감이 아닌 숫자로" 성능을 비교한다.
> 팀원은 이 명세서대로 실험을 실행하고 결과를 기록한다.

---

## 1. 실험 배경

이 프로젝트는 아래 4가지 성능 최적화를 순차적으로 적용했다.
벤치마크는 각 최적화의 **개별 기여도**를 분리 측정한다.

| 최적화 | 내용 | 관련 파일 |
|--------|------|-----------|
| **[A] 직렬 → 병렬** | `ThreadPoolExecutor`: embed ‖ keyword 동시 실행 | `news_service.py` |
| **[B] ILIKE → pg_trgm** | `word_similarity()` + GIN 인덱스 | `news_repository.py` |
| **[C] RRF 후보 수 제한** | Cross-Encoder 입력을 30~40건으로 제한 | `news_service.py` |
| **[D] Cross-Encoder** | `BAAI/bge-reranker-v2-m3` 리랭킹 | `reranker.py` |

---

## 2. 실험 설계

### 2-1. 실험 구성 (4가지)

| 실험 ID | 이름 | 병렬화 | 키워드 검색 | Reranker |
|---------|------|--------|------------|---------|
| **E1** | Baseline | ❌ 직렬 | ILIKE | ❌ |
| **E2** | +병렬화 | ✅ ThreadPoolExecutor | ILIKE | ❌ |
| **E3** | +pg_trgm | ❌ 직렬 | pg_trgm | ❌ |
| **E4** | 현재 구현 | ✅ ThreadPoolExecutor | pg_trgm | ❌ |

> **왜 E1~E4인가:** Cross-Encoder(D)는 검색 품질을 높이지만 지연 시간을 늘린다.
> 기반 지연 시간을 먼저 확정한 뒤 별도 품질 평가에서 Reranker 효과를 측정한다.

### 2-2. 테스트 쿼리 (고정)

아래 3가지 쿼리를 모든 실험에서 동일하게 사용한다.

| 쿼리 ID | 내용 | 특성 |
|---------|------|------|
| `Q1` | `"반도체 HBM 삼성 SK하이닉스"` | 짧고 명확한 기업명 포함 |
| `Q2` | `"금리 인상 물가 기준금리 한국은행"` | 경제 정책 복합어 |
| `Q3` | `"전기차 배터리 충전 인프라 보조금"` | 중간 길이, 복합 키워드 |

### 2-3. 측정 지표

| 지표 | 단위 | 측정 방법 |
|------|------|-----------|
| **평균 응답 시간** | ms | N회 반복 평균 |
| **중앙값 (P50)** | ms | 이상치 영향 최소화 |
| **P95** | ms | 최악 케이스 대리 지표 |
| **결과 건수** | 건 | `top_k` 충족 여부 확인 |

### 2-4. 반복 횟수 권고

```
최소: 3회  (빠른 확인)
권장: 5회  (통계적 안정성)
```

첫 1회는 **Warm-up으로 제외**한다 (DB 쿼리 캐시, 모델 초기화 영향).

---

## 3. 실행 방법

### 3-1. 사전 조건

```bash
# 1. 의존성 설치
uv sync

# 2. .env 파일 확인
cat .env   # DATABASE_URL, OPENAI_API_KEY 설정 필수

# 3. GIN 인덱스 확인 (pg_trgm 실험에 필요)
psql $DATABASE_URL -c "\d news_chunks"
# idx_chunks_trgm 인덱스가 있어야 pg_trgm이 빠름
```

### 3-2. 벤치마크 실행

```bash
# 기본 실행 (권장 5회, 기본 쿼리 3개)
python scripts/benchmark_search.py

# 반복 횟수 지정
python scripts/benchmark_search.py --repeat 10

# 커스텀 쿼리
python scripts/benchmark_search.py \
  --queries "삼성전자 반도체" "현대차 전기차" \
  --repeat 5

# 결과 파일 저장
python scripts/benchmark_search.py --repeat 5 --save
# → data/benchmark_results.json
```

### 3-3. 예상 출력

```
============================================================
  뉴스 검색 파이프라인 성능 벤치마크
============================================================
DB: postgresql://...  |  news_chunks: 335,073건
반복: 5회 (첫 1회 warm-up 제외)  |  쿼리: 3개

테스트 쿼리:
  [Q1] 반도체 HBM 삼성 SK하이닉스
  [Q2] 금리 인상 물가 기준금리 한국은행
  [Q3] 전기차 배터리 충전 인프라 보조금

============================================================
실험                         평균(ms)   P50(ms)   P95(ms)   결과수
------------------------------------------------------------
E1: 직렬 + ILIKE (베이스라인)    2,340     2,280     2,890      10
E2: 병렬 + ILIKE                1,420     1,380     1,680      10  (-39%)
E3: 직렬 + pg_trgm              1,980     1,940     2,200      10  (-15%)
E4: 병렬 + pg_trgm (현재)       1,050     1,020     1,190      10  (-55%)
============================================================

최적화 기여도 분해:
  병렬화 단독 효과   : -920ms (-39%)   [E1→E2]
  pg_trgm 단독 효과  : -360ms (-15%)   [E1→E3]
  복합 시너지 효과   : +230ms           [E2+E3보다 E4가 더 빠름]
============================================================
```

---

## 4. 결과 해석 기준

| 결과 | 해석 |
|------|------|
| E4 평균이 E1보다 **40% 이상** 감소 | 두 최적화 모두 효과 있음 ✅ |
| E2 평균이 E1보다 **20% 이상** 감소 | 병렬화 효과 확인 ✅ |
| E3 평균이 E1과 **차이 없음** | GIN 인덱스 미생성 가능성 → `\d news_chunks` 확인 |
| E4 결과 건수가 **top_k 미달** | pg_trgm threshold 너무 높음 → `_TRGM_THRESHOLD` 낮출 것 |

---

## 5. 구현 파일

| 파일 | 역할 |
|------|------|
| `scripts/benchmark_search.py` | 벤치마크 실행 스크립트 |
| `app/services/news_service.py` | `hybrid_search()` — E4 현재 구현 |
| `app/db/repositories/news_repository.py` | `search_chunks_by_keyword_ilike()` — E1/E2 베이스라인 |
| `data/benchmark_results.json` | 실험 결과 저장 (선택) |

---

## 6. AI Agent 지시사항

### 벤치마크 스크립트 작성 규칙

```python
# ✅ 올바른 측정 패턴
import time

times = []
for i in range(repeat + 1):       # +1 = warm-up 포함
    start = time.perf_counter()
    result = news_service.hybrid_search(query, top_k=10)
    elapsed = (time.perf_counter() - start) * 1000  # ms
    if i > 0:                      # 첫 warm-up 제외
        times.append(elapsed)

mean_ms = statistics.mean(times)
p50_ms  = statistics.median(times)
p95_ms  = sorted(times)[int(len(times) * 0.95)]
```

### DO
- 실험마다 동일한 쿼리, 동일한 `top_k`를 사용한다.
- Warm-up 1회를 반드시 제외한다.
- 실험 간 DB 연결을 재사용한다 (연결 비용 측정 제외).

### DON'T
- Warm-up 없이 첫 결과를 포함하지 않는다.
- 실험 중간에 서버 또는 DB를 재시작하지 않는다.
- 실험 결과를 맥락 없이 공유하지 않는다 (GIN 인덱스 유무, 하드웨어 스펙 명시 필수).
