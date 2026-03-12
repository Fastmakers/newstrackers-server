# 02_search_pipeline_spec.md — 검색 파이프라인 명세

> **이 문서는 `SPEC_SEARCH.md`를 대체하는 최신 명세입니다.**
> 구현 변경 시 코드보다 이 문서를 먼저 수정한다.

---

## 1. 데이터 소스

### 1-1. 테이블

| 테이블 | 건수 | 설명 |
|--------|------|------|
| `news_articles` | 188,379건 | 매일경제 원문 기사 (2024-12-22 ~ 2025-12-31) |
| `news_chunks` | 335,073건 | 청킹 + 임베딩 완료 (`chunk_version=v1_1000_180`) |

### 1-2. news_articles 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGINT PK | |
| `title` | TEXT | 기사 제목 |
| `body` | TEXT | 본문 전체 |
| `category_l2` | TEXT | 중분류 (기업/경제/IT·과학 등) |
| `published_at` | TIMESTAMPTZ | 발행일시 |
| `raw_metadata` | JSONB | `keyword_list` 포함 |

### 1-3. news_chunks 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGINT PK | |
| `article_id` | BIGINT FK | → news_articles.id |
| `chunk_no` | INTEGER | 0부터 시작 (0번 청크 = 제목 포함) |
| `chunk_text` | TEXT | 청크 본문 (평균 684자) |
| `embedding` | vector(1536) | text-embedding-3-small 벡터 |
| `chunk_version` | TEXT | `v1_1000_180` (1000자/180자 오버랩) |

**chunk_no=0 포맷:**
```
제목: {title}

{body 앞 1000자}
```

---

## 2. 도메인 모델

### NewsChunk (검색 반환 단위)
```python
class NewsChunk(BaseModel):
    id: int
    article_id: int
    chunk_no: int
    chunk_text: str
    chunk_chars: int
    article: NewsArticle | None   # JOIN 시 채워짐
```

### NewsArticle (NewsChunk.article)
```python
class NewsArticle(BaseModel):
    id: int
    title: str
    body: str
    source_name: str | None    # "매일경제" 고정
    category_l2: str | None
    published_at: datetime | None
    keyword_list: list[str]
```

---

## 3. 아키텍처 레이어 (데이터 흐름)

```
[PostgreSQL]
     │
     ▼
[NewsRepository]          ← SQL 쿼리만 담당 (비즈니스 로직 없음)
     │  adapter()
     ▼
[Domain Model]            ← 순수 Python 객체 (Pydantic)
     │
     ▼
[NewsService]             ← 검색 오케스트레이션 (V1 / V2 / V3)
     │
     ▼
[API Endpoint]            ← HTTP 직렬화
```

---

## 4. 검색 버전별 명세

### 4-1. V1 — 벡터 검색 (Baseline)

**함수:** `NewsService.vector_search(query, company, category_l2, top_k)`

```
query
  └─► embed_query()  → OpenAI text-embedding-3-small → 1536차원 벡터
          │
          ▼
  _vector_search_chunks()  → pgvector cosine distance <=>
          │  limit=100
          ▼
  _title_boost()  → 제목에 company 포함 시 +0.3 보너스 재정렬
          │
          ▼
  _dedup(top_k)   → article_id 기준 중복 제거 후 top_k 반환
```

**언제 사용:** 쿼리가 자소서 원문처럼 길고, 특정 기업명으로 결과를 편향시킬 때.

---

### 4-2. V2 — 하이브리드 검색 (기본값)

**함수:** `NewsService.hybrid_search(query, keyword_query, category_l2, top_k)`

```
query ──────────────────────────────────────────── ThreadPoolExecutor(max_workers=3)
  │                                                              │
  ├─► [Thread A] embed_query()                                   │
  │       └─► 완료 즉시 [Thread C] _vector_search_chunks() 시작 │
  │                                                              │
  └─► [Thread B] _keyword_search_chunks() (pg_trgm)             │
              (Thread A와 동시 시작 — I/O 겹침)                  │
                                                                 │
  Thread B 결과 ──────────────┐                                  │
  Thread C 결과 ──────────────┤                                  │
                              ▼                                  │
                      rrf_fuse(k=60)                             │
                          top_n=100                              │
                              │                                  │
                              ▼                                  │
                      _dedup(top_k)                             ─┘
```

**병렬 처리 규칙:**
1. `embed_query`와 `_keyword_search_chunks`는 **동시에** 시작한다.
2. 임베딩이 완료된 **직후** `_vector_search_chunks`를 시작한다.
3. 각 Thread는 **독립적인 DB 세션**을 사용한다 (세션 공유 금지).

**pg_trgm 키워드 검색 규칙:**
- `word_similarity(query, chunk_text)` 기반
- 제목 유사도 2배 가중: `title_score * 2 + chunk_score`
- `_TRGM_THRESHOLD = 0.05` (매우 낮음 — 리스트는 ORDER BY로 정렬이 핵심)
- **GIN 인덱스 필수**: `idx_chunks_trgm` (없으면 Seq Scan으로 수 초 지연)

---

### 4-3. V3 — Cross-Encoder 리랭킹

**함수:** `NewsService.rerank_chunks(query, chunks, top_k)`

```
hybrid_search 결과 (V2)
  │  최대 _V3_RERANK_POOL=40건을 입력으로 전달 (전체 사용 금지)
  ▼
CrossEncoderReranker.rerank(query, chunks[:40], top_n=top_k)
  │
  ├─ 입력: (query, "제목: {title}\n{chunk_text}") 쌍 × 40
  ├─ 모델: BAAI/bge-reranker-v2-m3 (lazy-load, 첫 호출 시 ~1.1GB 로드)
  └─ 출력: Cross-Encoder 점수 내림차순 → top_k
```

**V3 사용 조건:**
- `sentence-transformers>=3.0.0` 설치 필요
- 충분한 GPU/CPU 메모리 확보 (모델 ~1.1GB)
- 현재 기본 비활성화 — 코드 내에서 명시적으로 `rerank_chunks()` 호출 필요

**V3 호출 패턴:**
```python
# search.py endpoint 예시
candidates = news_service.hybrid_search(query, top_k=40)
results = news_service.rerank_chunks(query, candidates, top_k=10)
```

---

## 5. RRF 융합 알고리즘 명세

**파일:** `app/services/search/rrf.py`

```python
score(chunk) = Σ_i  1 / (k + rank_i(chunk))
```

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| `k` | 60 | 표준 RRF 하이퍼파라미터 |
| `top_n` | 100 | 융합 후 반환할 최대 건수 |

- `rank_i`가 없는 경우 (한 쪽에만 있는 청크): 해당 항목의 점수만 사용.
- chunk_id 기준으로 두 결과 리스트를 합산.

---

## 6. 중복 제거 (_dedup) 규칙

**동일 article_id**에서 여러 청크가 나올 수 있으므로 제거한다.
- 순위가 높은 청크(먼저 나온 것)를 유지.
- `article_id` 기준 first-seen 방식.

```python
seen: set[int] = set()
for chunk in ranked_chunks:
    if chunk.article_id not in seen:
        seen.add(chunk.article_id)
        result.append(chunk)
        if len(result) == top_k:
            break
```

---

## 7. 카테고리 필터 (`category_l2`)

| 값 | 기사 수 |
|----|---------|
| `기업` | 28,599 |
| `사회` | 26,234 |
| `경제` | 16,209 |
| `정치` | 15,124 |
| `증권` | 13,819 |
| `국제` | 12,746 |
| `문화` | 11,553 |
| `IT·과학` | 9,001 |
| `부동산` | 6,926 |
| `스포츠` | 3,059 |

`None`이면 전체 검색.

---

## 8. 구현 파일 맵

| 파일 | 역할 |
|------|------|
| `app/db/models.py` | SQLAlchemy ORM (NewsArticleDB, NewsChunkDB) |
| `app/db/adapters/news_adapter.py` | DB Row → Domain Model |
| `app/db/repositories/news_repository.py` | SQL 쿼리 (벡터/pg_trgm/ILIKE) |
| `app/schemas/data_models.py` | Pydantic 도메인 모델 |
| `app/services/news_service.py` | V1 `vector_search`, V2 `hybrid_search`, V3 `rerank_chunks` |
| `app/services/search/rrf.py` | RRF 융합 |
| `app/services/search/reranker.py` | Cross-Encoder (BAAI/bge-reranker-v2-m3) |

---

## 9. 구현 상태 체크리스트

- [x] `models.py` — ORM 정의
- [x] `news_adapter.py` — Row → Domain 변환
- [x] `news_repository.py`
  - [x] `search_chunks_by_vector()` — pgvector cosine distance
  - [x] `search_chunks_by_keyword()` — pg_trgm word_similarity (GIN 인덱스 필요)
  - [x] `search_chunks_by_keyword_ilike()` — ILIKE 베이스라인 (벤치마크용)
- [x] `rrf.py` — RRF 융합 (k=60)
- [x] `reranker.py` — Cross-Encoder (lazy-load)
- [x] `news_service.py`
  - [x] `vector_search()` — V1
  - [x] `hybrid_search()` — V2 (ThreadPoolExecutor + pg_trgm)
  - [x] `rerank_chunks()` — V3 entry point
  - [x] `_dedup()` — article_id 기준 중복 제거
  - [x] `_title_boost()` — 기업명 제목 보너스
- [x] **DB GIN 인덱스 생성** — `idx_chunks_trgm` (생성 완료 — 키워드 검색 2배+ 속도 향상 확인)
- [ ] `search.py` endpoint — `/api/v1/search` (hybrid_search 연동)

---

## 10. AI Agent 지시사항

### DO
- `search_chunks_by_keyword_ilike()`는 **벤치마크 비교 전용**으로만 사용한다.
- 새 검색 로직 추가 시 이 명세서를 먼저 업데이트한 후 구현한다.
- V3 사용 코드는 `rerank_chunks()` 호출 전 `chunks[:_V3_RERANK_POOL]`로 개수를 제한한다.

### DON'T
- `search_chunks_by_keyword_ilike()`를 프로덕션 검색 경로에 사용하지 않는다.
- `hybrid_search()` 내부에서 DB 세션을 공유하지 않는다 (Thread마다 독립 세션).
- Cross-Encoder에 100건 이상을 입력하지 않는다 (지연 시간 폭발적 증가).
