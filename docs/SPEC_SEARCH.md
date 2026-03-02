# 검색 파이프라인 스펙

> 이 문서를 기준으로 구현하고, 변경 시 문서를 먼저 수정한다.

## 1. 데이터 소스

### 1-1. DB 테이블

| 테이블 | 설명 | 건수 |
|--------|------|------|
| `news_articles` | 매일경제 원문 기사 | 188,379 |
| `news_chunks` | 청킹 + 임베딩 완료본 | 335,073 |

### 1-2. news_articles 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGINT PK | |
| `source_article_id` | TEXT | 매경 원문 ID |
| `source_name` | TEXT | 기자명 + 이메일 (예: `홍길동 기자(gil@mk.co.kr)`) |
| `title` | TEXT | 기사 제목 |
| `summary` | TEXT | 요약 (매경 제공) |
| `body` | TEXT | 본문 전체 |
| `article_url` | TEXT | 원문 URL |
| `category_l1` | TEXT | 대분류 (뉴스 / 스타투데이 / 오피니언) |
| `category_l2` | TEXT | 중분류 (기업 / 정치 / 경제 / IT·과학 …) |
| `category_l3` | TEXT | 소분류 |
| `writer` | TEXT | 기자명 (source_name과 동일) |
| `lang` | TEXT | 언어 (`KR`) |
| `published_at` | TIMESTAMP TZ | 발행일시 (2024-12-22 ~ 2025-12-31) |
| `raw_metadata` | JSONB | 원본 메타 (keyword_list, article_summary 등) |
| `content_hash` | TEXT | 중복 체크용 해시 |

### 1-3. news_chunks 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | BIGINT PK | |
| `article_id` | BIGINT FK | → news_articles.id |
| `chunk_version` | TEXT | `v1_1000_180` (1000자, 180자 오버랩) |
| `chunk_no` | INTEGER | 청크 순번 (0부터 시작) |
| `chunk_text` | TEXT | 청크 본문 (avg 684자) |
| `chunk_chars` | INTEGER | 글자 수 |
| `chunk_tokens_est` | INTEGER | 추정 토큰 수 |
| `section_type` | TEXT | `body` (현재 전부 body) |
| `embedding_model` | TEXT | `text-embedding-3-small` |
| `embedding` | vector(1536) | 임베딩 벡터 (전량 완료) |

---

## 2. 도메인 모델

### NewsArticle (도메인)
```python
class NewsArticle:
    id: int
    title: str
    summary: str | None
    body: str
    source_name: str | None      # 언론사명 (기자 정보 제거 후)
    writer: str | None           # 기자명 (정규화 후)
    article_url: str | None
    category_l1: str | None
    category_l2: str | None
    published_at: datetime | None
    keyword_list: list[str]      # raw_metadata.keyword_list
```

### NewsChunk (도메인)
```python
class NewsChunk:
    id: int
    article_id: int
    chunk_no: int
    chunk_text: str
    chunk_chars: int
    article: NewsArticle | None  # JOIN 시
```

---

## 3. 어댑터 패턴

```
[DB Row]
   │
   ▼
[Repository]  ─ SQL 쿼리 담당, DB 상세를 은닉
   │
   ▼ adapter()
[Domain Model]  ─ 비즈니스 로직이 사용하는 순수 Python 객체
   │
   ▼
[Service]  ─ 검색/분석 오케스트레이션
   │
   ▼
[API Endpoint]
```

---

## 4. 검색 파이프라인 스펙 (3단계 하이브리드)

### 입력
```python
query: str          # 검색어 또는 자소서 요약 키워드
category_l2: str    # 선택 필터 (기업 / 경제 / IT·과학 …)
top_k: int = 5      # 최종 반환 건수
```

### 4-1. 1단계: 병렬 검색 (각 100건)

| 방법 | 구현 | 대상 컬럼 |
|------|------|----------|
| **벡터 검색** | pgvector `<=>` 코사인 거리 | `news_chunks.embedding` |
| **키워드 검색** | `ILIKE` (추후 BM25로 교체) | `news_articles.title`, `body` |

```
query → embed_query() → vector_results[100]
query → keyword_search() → keyword_results[100]
```

### 4-2. 2단계: RRF 융합 (→ 100건)

```python
# Reciprocal Rank Fusion
score(d) = Σ 1 / (k + rank_i(d))   # k=60 (표준)
```

chunk_id 기준으로 두 결과를 합산 → 상위 100건 추출.

### 4-3. 3단계: Cross-Encoder 리랭킹 (→ top_k건)

- 모델: `BAAI/bge-reranker-m3`
- 입력: `(query, chunk_text)` 쌍 100개
- 출력: 정밀 점수 → 상위 `top_k`건

### 출력
```python
list[NewsChunk]   # article 정보 JOIN 포함
```

---

## 5. 카테고리 필터 스펙

category_l2 유효값:

| 값 | 건수 |
|----|------|
| 기업 | 28,599 |
| 사회 | 26,234 |
| 경제 | 16,209 |
| 정치 | 15,124 |
| 증권 | 13,819 |
| 국제 | 12,746 |
| 문화 | 11,553 |
| IT·과학 | 9,001 |
| 부동산 | 6,926 |
| 스포츠 | 3,059 |

---

## 6. 데이터 정제 스펙

### 6-1. writer 정규화 (source_name → 기자명)
- 입력: `"홍길동 매경 디지털뉴스룸 기자(gil@mk.co.kr)"`
- 출력: `"홍길동"`
- Regex: `^(\S+)\s+.*기자.*$`

### 6-2. source_name → 언론사명
- 입력: `"홍길동 매경 디지털뉴스룸 기자(gil@mk.co.kr)"`
- 출력: `"매경"`
- 전부 매일경제이므로 고정값 `"매일경제"` 사용

### 6-3. keyword_list 추출
- `raw_metadata['keyword_list']` → `list[str]`
- None이면 `[]`

---

## 7. 구현 파일 맵

| 파일 | 역할 |
|------|------|
| `app/db/models.py` | SQLAlchemy ORM (NewsArticleDB, NewsChunkDB) |
| `app/db/repositories/news_repository.py` | DB 쿼리 캡슐화 |
| `app/db/adapters/news_adapter.py` | DB Row → Domain Model 변환 |
| `app/schemas/data_models.py` | Domain Model (Pydantic) |
| `app/services/news_service.py` | 검색 오케스트레이션 |
| `app/services/search/vector_search.py` | 벡터 검색 |
| `app/services/search/keyword_search.py` | 키워드 검색 |
| `app/services/search/rrf.py` | RRF 융합 |
| `app/services/search/reranker.py` | Cross-Encoder 리랭킹 |

---

## 8. 구현 체크리스트

- [x] `models.py` — NewsArticleDB, NewsChunkDB ORM 정의
- [x] `news_adapter.py` — DB Row → Domain 변환
- [x] `news_repository.py` — 벡터 검색, 키워드 검색 쿼리 (chunk 레벨 포함)
- [x] `news_service.py` — 리포지토리 조합 + RRF (`hybrid_search()`)
- [x] `rrf.py` — Reciprocal Rank Fusion (k=60 표준)
- [x] `fetch_nodes.py` — 새 news_service 연동 (기존 코드 호환)
- [ ] `keyword_search.py` — BM25로 교체 (현재 ILIKE)
- [ ] `reranker.py` — Cross-Encoder (BAAI/bge-reranker-m3)
- [ ] API 엔드포인트 — `/search` 엔드포인트 추가 (hybrid_search 연동)
