# 뉴스 기사 처리 파이프라인

매일경제 뉴스 기사 한 건이 RAG 검색 결과로 나오기까지 거치는 모든 단계를 기록한다.

---

## 전체 흐름

```
[DB: news_articles]  187,884건
        │
        ▼
┌─────────────────────────────────────┐
│  Phase 1. 데이터 품질 필터링          │  (오프라인 배치 스크립트)
│  - TextCleaner                      │
│  - LexicalDiversityAnalyzer         │
└─────────────────────────────────────┘
        │  정상 기사 ~172,847건 (92%)
        ▼
┌─────────────────────────────────────┐
│  Phase 2. NLP 분석 (오프라인 배치)    │
│  - NgramExtractor (TF-IDF)          │
│  - NerExtractor (NER/POS)           │
└─────────────────────────────────────┘
        │  data/ngrams.json, data/ner_result.json
        ▼
┌─────────────────────────────────────┐
│  Phase 3. 벡터 임베딩 (이미 완료)     │  (news_chunks 테이블)
│  - text-embedding-3-small (1536d)   │
│  - chunk_version = v1_1000_180      │
└─────────────────────────────────────┘
        │  news_chunks 335,073건
        ▼
┌─────────────────────────────────────┐
│  Phase 4. 하이브리드 검색 (실시간)    │  (사용자 쿼리 입력 시)
│  - 쿼리 3개 병렬 생성                │
│  - 벡터 검색 (pgvector) × 3         │
│  + 키워드 검색 (pg_trgm) × 3        │
│  → RRF 다중 융합 → top-15청크       │
└─────────────────────────────────────┘
        │  top-K 청크
        ▼
┌─────────────────────────────────────┐
│  Phase 5. LLM 분석 (실시간)          │
│  LLMService (app/services/)         │
│  - extract_trends / extract_keywords │
│  - generate_swot_list               │
│  - generate_relevance_analysis      │
│  - generate_final_report            │
└─────────────────────────────────────┘
        │
        ▼
    API 응답 (JSON)
```

---

## Phase 1. 데이터 품질 필터링

### 1-1. TextCleaner — `app/analysis/text_cleaner.py`

기사 본문에서 내용과 무관한 노이즈를 Regex로 제거한다.

| 제거 대상 | 예시 |
|---|---|
| 이메일 주소 | `reporter@mk.co.kr` |
| URL | `https://www.mk.co.kr/news/123` |
| 저작권 고지 | `ⓒ 매일경제 & mk.co.kr, 무단전재 및 재배포 금지` |
| 사진 출처 태그 | `[사진 = 연합뉴스]`, `[사진출처=게티이미지]` |
| 통신사 태그 | `[AP=연합뉴스]`, `[매경DB]` |
| 기자 바이라인 | `홍길동 기자`, `홍길동 특파원` |
| 중복 공백·개행 | `단어1   단어2` → `단어1 단어2` |

**적용 시점**: `LexicalDiversityAnalyzer`, `NgramExtractor`, `NerExtractor` 내부에서 자동 호출됨.

---

### 1-2. LexicalDiversityAnalyzer — `app/analysis/lexical_diversity.py`

kiwipiepy로 명사를 추출한 뒤 **LogTTR (Herdan's C)** 을 계산해 노이즈 기사를 탐지한다.

```
LogTTR = log(고유 단어 수) / log(전체 단어 수)
```

길이가 길어질수록 TTR(Type-Token Ratio)이 떨어지는 편향을 로그 스케일로 보정한다.

**노이즈 분류 규칙:**

| 조건 | 분류 | 이유 |
|---|---|---|
| 명사 토큰 < 50개 | 노이즈 (토큰 부족) | 단신·포토 캡션·헤드라인 나열 |
| 고유 단어 = 1개 | 노이즈 (어휘 단일화) | 완전 반복 스팸 |
| LogTTR < 0.82 | 노이즈 (반복 패턴) | 브랜드지수 나열, 증권 시황 반복 |
| LogTTR > 0.99 | 노이즈 (파싱 오류) | [포토] 기사, 해시값, 극단 단신 |

**매경 2025 실측 분포:**
- mean = 0.9096, std = 0.0248
- 정상 범위: 0.82 ~ 0.99 (전체의 91.3%)
- 노이즈: 15,037건 (8.7%)
  - 토큰 부족 (포토·단신): 14,614건
  - 반복 패턴: ~423건

**실행 스크립트:**
```bash
python scripts/analyze_lexical_diversity.py --all --save
# → data/lexical_diversity.json (noise_article_ids 포함)
```

---

## Phase 2. NLP 분석 (오프라인 배치)

### 2-1. NgramExtractor — `app/analysis/ngram_extractor.py`

kiwipiepy 명사 추출 → scikit-learn **TfidfVectorizer** → 카테고리별 핵심 키워드.

**설계 파라미터 (`NgramConfig`):**

| 파라미터 | 기본값 | 의미 |
|---|---|---|
| `max_features` | 1000 | 상위 N개 키워드만 추출 |
| `ngram_range` | (1, 2) | 단어 + 바이그램 |
| `min_df` | 5 | 최소 5개 기사에서 등장해야 유효 |
| `use_tfidf` | True | False면 단순 빈도(CountVectorizer) |

**단어 vs 바이그램 차이:**

| 단어 (1-gram) | 바이그램 (2-gram) |
|---|---|
| `인공지능` | `인공지능 서버` |
| `반도체` | `반도체 수출` |
| `금리` | `금리 인상` |

바이그램이 산업 맥락을 훨씬 정확하게 포착한다.

**실행 스크립트:**
```bash
python scripts/extract_ngrams.py --category 경제 --n 10000 --save
python scripts/extract_ngrams.py --all --save
# → data/ngrams.json
```

---

### 2-2. NerExtractor — `app/analysis/ner_extractor.py`

kiwipiepy POS 태그 + 휴리스틱 규칙으로 개체명을 분류한다.

**POS 태그 → 개체 유형 분류 흐름:**

```
NNP(고유명사) 토큰
    │
    ├─ 알려진 지명 목록에 있음 (미국, 서울, ...) → LOC
    ├─ ~국/시/구/도 접미어                       → LOC
    ├─ 뒤 토큰이 회장/장관/교수/대표 등           → PERSON
    ├─ ~전자/은행/그룹/협회 등 ORG 접미어         → ORG
    └─ 나머지                                   → MISC
```

**동사(산업 동인) 추출:**

```
VV 태그                      → "오르다", "하락하다"
NNG + XSV("하") 복합동사      → "급증하다", "발표하다", "합병하다"
```

**실행 스크립트:**
```bash
python scripts/extract_ner.py --category 경제 --n 5000
python scripts/extract_ner.py --all --save
# → data/ner_result.json
```

---

## Phase 3. 벡터 임베딩 (이미 완료)

기사 본문을 청크로 분할 후 OpenAI `text-embedding-3-small`로 임베딩.

| 항목 | 값 |
|---|---|
| 임베딩 모델 | `text-embedding-3-small` |
| 벡터 차원 | 1536 |
| 청크 전략 | 1000자 / 180자 오버랩 (`v1_1000_180`) |
| chunk_no=0 형식 | `"제목: {title}\n\n{body_start}"` |
| 총 청크 수 | 335,073건 |

**관련 파일:**
- `app/db/models.py` — NewsChunkDB (SQLAlchemy ORM)
- `app/db/repositories/news_repository.py` — 청크 검색 쿼리

---

## Phase 4. 하이브리드 검색 (실시간)

사용자가 검색어를 입력하면 실시간으로 실행된다.

### `NewsService.multi_hybrid_search(queries, keyword_query, top_k)`

쿼리 3개를 ThreadPoolExecutor로 병렬 실행 후 RRF로 합산한다.

```
쿼리 3개 (transform_query 결과)
    │
    ├─── [쿼리1] Stage 1A: 벡터 검색 (pgvector cosine)  → top-100
    │            Stage 1B: 키워드 검색 (pg_trgm)        → top-100
    │            → RRF 융합 → 100건
    │
    ├─── [쿼리2] 동일                                   → 100건
    │
    ├─── [쿼리3] 동일                                   → 100건
    │
    ▼
    rrf_fuse_multi(3개 결과)  — app/services/search/rrf.py
        score(d) = Σ 1/(k=60 + rank_i)
    │
    ▼
    top_k 청크 반환 (기본 15건)
```

**관련 파일:**
- `app/services/news_service.py` — `hybrid_search()`
- `app/services/search/rrf.py` — RRF 융합 알고리즘
- `app/db/repositories/news_repository.py` — `search_similar_chunks()`, `search_chunks_by_keyword()`

---

## Phase 5. LLM 분석 (실시간)

검색된 청크를 컨텍스트로 Claude에게 분석을 요청한다.
모든 LLM 호출은 `app/services/llm_service.py` (`LLMService`) 에서 처리한다.

### 종합 리포트 — Pipeline E (`POST /jobs` → Worker → `ReportPipeline.run_with_progress`)

```
자소서 PDF 텍스트
    │
    ▼
Step 1. analyze_resume(resume_text)                        [Claude Haiku]
    → skills[], experience_keywords[], target_role
    │
    ▼
Step 2. transform_query(company, job_title, industry,      [Claude Haiku]
                        skills, experience_keywords)
    → queries: ["기업 전략 쿼리", "도메인 기술 쿼리", "직무 시장 쿼리"]
    │
    ▼
Step 3. multi_hybrid_search(queries × 3 병렬, keyword_query=기업명)
    │  ThreadPoolExecutor (쿼리당 hybrid_search 병렬 실행)
    │  각 hybrid_search: 벡터 검색 || 키워드 검색 → RRF
    │  최종: rrf_fuse_multi(3개 결과) → top-15 청크
    │
    ├─────────────────────────────────────┐
    ▼                                     ▼
Step 4a. generate_swot_list(             Step 4b. generate_relevance_analysis(
    resume, company, job_title,              resume, chunks, company,
    chunks, industry, career_level)          industry, job_title, career_level)
    → Dict[str, List[str]]  [Sonnet]         → markdown string  [Sonnet]
    │                                     │
    └──────────────┬──────────────────────┘
                   ▼
Step 5. generate_final_report(resume, company, job_title,  [Claude Sonnet]
                               industry, swot, relevance_analysis)
    → markdown string
    │
    ▼
ReportResponse 조립 → DB 저장 (analysis_reports)
```

**진행률 콜백 (on_step):**

| step | pct | 포함 데이터 |
|------|-----|------------|
| 1 | 20% | resume_profile |
| 3 | 50% | matched_news |
| 4 | 80% | swot, relevance_analysis |
| 5 | 100% | final_report |

**쿼리 생성 전략 (transform_query):**
- 쿼리 1: 기업 전략/사업 방향 — 기업 레벨 뉴스
- 쿼리 2: 지원자 도메인 기술이 해당 기업/산업에 적용되는 방식
- 쿼리 3: 직무 × 기업이 교차하는 시장 변화
- 모든 쿼리는 기업명 또는 기업 핵심 사업과 연결 (개인 기술스택 제외)

**LLM 모델:** `claude-sonnet-4-6` (분석), `claude-haiku-4-5` (빠른 전처리)

