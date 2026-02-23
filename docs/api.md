# API 엔드포인트 문서

Base URL: `http://localhost:8000`

---

## 헬스체크

### `GET /health`
```json
{ "status": "healthy" }
```

---

## 자소서 분석 API `/api/v1/analysis`

### `POST /api/v1/analysis/report`

자소서 PDF를 업로드하면 LangGraph 파이프라인을 통해 4단계 분석을 수행하고 결과를 반환합니다.

**요청:** `multipart/form-data`

| 필드 | 타입 | 설명 |
|------|------|------|
| `file` | File (PDF) | 자소서 PDF 파일 |

**응답:**
```json
{
  "status": "success",
  "resume_profile": {
    "job_title": "백엔드 개발자",
    "industry": "AI 인공지능",
    "company": "카카오",
    "skills": ["Python", "FastAPI", "PostgreSQL"],
    "experiences": ["스타트업 서버 개발 2년", "오픈소스 기여"]
  },
  "matched_news_count": 12,
  "matched_news": [
    {
      "id": "a1b2c3d4e5f67890",
      "title": "생성 AI 스타트업 국내 투자 급증",
      "url": "https://example.com/news/456",
      "job_category": "AI 인공지능",
      "published_at": "2026-02-15T09:00:00+00:00",
      "distance": 0.187
    }
  ],
  "relevance_analysis": "최근 AI 인공지능 산업에서는...",
  "swot": {
    "strengths": ["FastAPI 실무 경험이 AI 백엔드 수요와 일치", "..."],
    "weaknesses": ["LLM 파인튜닝 경험 부재", "..."],
    "opportunities": ["국내 생성 AI 투자 급증으로 백엔드 인력 수요 폭증", "..."],
    "threats": ["동일 스택 지원자 경쟁 심화", "..."]
  },
  "final_report": "# 취업 지원 분석 보고서\n\n## 지원자 프로필\n..."
}
```

**에러 응답:**
- `415` - PDF가 아닌 파일 업로드 시
- `422` - 이미지 기반 PDF 또는 텍스트 추출 불가 시
- `500` - 파이프라인 내부 오류

---

## 뉴스 검색 API `/api/v1/news`

### `GET /api/v1/news/search`

pgvector 유사도 검색으로 관련 뉴스를 조회합니다.

**Query Parameters:**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
|----------|------|------|--------|------|
| `query` | string | O | - | 검색 쿼리 |
| `industry` | string | X | null | 산업군 필터 |
| `limit` | int | X | 10 | 결과 개수 (1~50) |

**응답:**
```json
{
  "query": "반도체 수출 동향",
  "industry": "반도체",
  "count": 5,
  "results": [
    {
      "id": "a1b2c3d4e5f67890",
      "document": "[반도체] 삼성전자...\n기사 본문...",
      "metadata": {
        "title": "삼성전자 반도체 수출 호조",
        "url": "https://example.com/news/123",
        "job_category": "반도체",
        "published_at": "2026-02-17"
      },
      "distance": 0.234
    }
  ]
}
```

---

### `GET /api/v1/news/stats`

Vector DB 통계를 반환합니다.

**응답:**
```json
{
  "total_documents": 1500,
  "industries": ["반도체", "AI 인공지능", "..."]
}
```

---

### `GET /api/v1/news/industries`

설정된 산업군 목록을 반환합니다.

**응답:**
```json
{
  "industries": [
    "반도체", "AI 인공지능", "금융", "제조업", "바이오 헬스케어",
    "유통 커머스", "콘텐츠 미디어", "에너지 환경", "자동차 모빌리티", "건설 부동산"
  ]
}
```
