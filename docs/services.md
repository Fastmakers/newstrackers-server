# 서비스 및 에이전트 모듈 상세 문서

---

## Services (`app/services/`)

### 1. `pdf_extractor.py` — PDF 텍스트 추출

PyMuPDF(`fitz`)를 사용하여 자소서 PDF에서 텍스트를 추출합니다.

| 함수 | 설명 |
|------|------|
| `extract_text_from_pdf(pdf_bytes: bytes) -> str` | PDF 바이트 → 텍스트 추출. 암호화/이미지 PDF 시 ValueError |

**특징:**
- Korean CJK 폰트 네이티브 지원
- 읽기 순서(top-to-bottom) 보존
- 최소 50자 미만이면 이미지 PDF로 판단하여 예외 발생

---

### 2. `claude_llm.py` — Claude API 클라이언트

`anthropic.AsyncAnthropic` 기반 싱글톤 서비스. 노드에서 `claude_llm_service.client`로 직접 호출합니다.

| 메서드 | 설명 | max_tokens |
|--------|------|------------|
| `summarize_news(title, content, industry)` | 뉴스 1건 요약 (3~5문장) | 500 |
| `analyze_industry_trends(news_texts, industry)` | 산업 트렌드 분석 | 1000 |

---

### 3. `vector_store.py` — pgvector 벡터 검색 (읽기 전용)

asyncpg 커넥션 풀 + pgvector 기반. `news_article_embeddings` 테이블을 읽기 전용으로 사용합니다.

| 메서드 | 설명 |
|--------|------|
| `init_db()` | 커넥션 풀 생성 |
| `close()` | 커넥션 풀 종료 |
| `search(query, n_results)` | 코사인 거리 기반 유사도 검색 |
| `get_stats()` | 총 문서 수 반환 |

**임베딩:** OpenAI `text-embedding-3-small` (1536차원) — 쿼리 임베딩 생성에만 사용

---

## Agents (`app/agents/`)

### `state.py` — LangGraph 상태 정의

```python
class ResumeProfile(TypedDict):
    job_title: str       # 지원 직무
    industry: str        # INDUSTRY_KEYWORDS 중 하나
    company: str         # 지원 회사
    skills: list[str]    # 보유 스킬/역량
    experiences: list[str]  # 경험/프로젝트

class AnalysisState(TypedDict):
    resume_text: str                          # PDF 원문 (입력)
    resume_profile: Optional[ResumeProfile]   # Node 1 출력
    matched_news: Optional[list[dict]]        # Node 2 출력
    relevance_analysis: Optional[str]         # Node 3 출력
    swot: Optional[dict[str, list[str]]]      # Node 4 출력
    final_report: Optional[str]               # Node 4 출력
    error: Optional[str]
```

---

### `analysis_graph.py` — LangGraph 그래프 싱글톤

import 시점에 컴파일되어 전역 싱글톤으로 재사용됩니다.

```
analyze_resume → match_keywords → analyze_relevance → generate_report → END
```

---

### Node 1: `nodes/analyze_resume.py`

- Claude에 자소서 텍스트 전달
- `settings.INDUSTRY_KEYWORDS`를 프롬프트에 주입 → industry 값 강제 제한
- JSON 응답 파싱 (```json 펜스 자동 처리) → `ResumeProfile`
- 예외 시 `state["error"]` 세팅

---

### Node 2: `nodes/match_keywords.py`

- 검색 쿼리 5개: `[industry, "{industry} {job_title}", skill1, skill2, skill3]`
- 각 쿼리: `vector_store_service.search(query, n_results=5)`
- ID 중복 제거 → distance 오름차순 → 최대 15건

---

### Node 3: `nodes/analyze_relevance.py`

- 매칭 뉴스 최대 15건 + 지원자 프로필 → Claude 전달
- 출력: 산업 동향 + 지원자 스킬/경험과의 연관성 분석 (한국어 산문)
- `max_tokens=1500`

---

### Node 4: `nodes/generate_report.py`

- **1차 Claude 호출**: SWOT 분석 → 순수 JSON 강제 출력 후 파싱
  ```json
  {"strengths": [...], "weaknesses": [...], "opportunities": [...], "threats": [...]}
  ```
- **2차 Claude 호출**: 전체 컨텍스트로 종합 마크다운 리포트 생성
  - 섹션: 지원자 프로필 요약 / 산업 동향 / SWOT / 면접 준비 포인트 / 최종 권고사항
- `max_tokens=2000`
