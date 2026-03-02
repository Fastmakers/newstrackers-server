# NewStrackers Server - Project SPEC Document

**Version:** 1.0  
**Date:** 2026-02-16  
**Status:** Implementation Phase

---

## 1. PROJECT EXECUTIVE SUMMARY

### Overview
**"NewStrackers AI"** is an intelligent job interview and career development platform that combines user resumes (Internal Context) with real-time industry news/trends (External Context) to provide:

1. **Industry Insight Dashboard**: Data-driven trend analysis based on 1-year news history
2. **Corporate Interview Preparation**: Company-specific analysis with AI-generated interview questions
3. **Market Intelligence**: Real-time SWOT analysis, sentiment tracking, and competitive positioning

### Core Value Proposition
- **Not just information retrieval**, but personalized strategic analysis from the user's perspective
- **Contextual intelligence**: News + Resume → Actionable interview strategies
- **Real-time data**: Live news integration ensures up-to-date market positioning

### Target Users
- Job seekers preparing for technical interviews
- Career changers researching new industries
- Professionals tracking industry trends

### Success Metrics
- News data freshness: < 48 hours
- AI response latency: < 5 seconds
- User satisfaction with generated interview questions (target: 4.5/5)

---

## 2. FUNCTIONAL REQUIREMENTS

### Feature 1: Industry Trend Analysis
**Purpose**: Provide comprehensive industry overview through news-driven insights

#### Inputs
- **Industry Selection**: Dropdown with predefined sectors (반도체, 이차전지, AI/ML, 금융, 헬스케어, 에너지 등)
- **Time Period**: Default 1 year, customizable

#### Process
1. **Trend Extraction**: NLP analysis of 1-year news articles to identify 3 major industry trends
2. **Keyword Classification**: Categorize keywords into:
   - **Tech** (기술): Technologies, innovations (파랑색)
   - **Corp** (기업): Company activities, M&A (초록색)
   - **Policy** (정책): Regulations, subsidies (주황색)
3. **Sentiment Analysis**: Monthly sentiment tracking with issue intensity

#### Outputs
- **Dynamic WordCloud**: Size based on frequency/weight, color by category
- **Sentiment Heatmap**: Monthly trend with intensity and score visualization
- **Trend Summary**: 3 bullet-point industry insights
- **Top Keywords**: Table with type, weight, and interpretation

#### Data Flow
```
News API → Processing Pipeline → NLP Analysis → Aggregation → Visualization
```

---

### Feature 2: Corporate Interview Preparation
**Purpose**: Generate strategic interview questions and answers tailored to a company

#### Inputs
- **Company Name**: Selected from top companies in chosen industry
- **Resume/CV Text**: User's background, skills, experience
- **Interview Type**: Technical/HR/Leadership (optional, default: mixed)

#### Process
1. **Company News Analysis**: 
   - Fetch 1-year company-specific news articles
   - Extract key events, achievements, crises

2. **5-Dimension Scoring**:
   - 성장성 (Growth): Revenue/market expand trends
   - 안정성 (Stability): Consistent performance, no major crises
   - 혁신성 (Innovation): R&D, new products/services
   - ESG: Environmental, social governance initiatives
   - 시장점유율 (Market Share): Competitive positioning

3. **SWOT Analysis**: 
   - Strengths: From positive news, achievements
   - Weaknesses: From challenges, crises
   - Opportunities: Emerging trends in industry
   - Threats: Competitive pressure, regulations

4. **RAG-based Q&A Generation**:
   - Context: Company news + User resume
   - Generate killer interview questions that blend company challenges with user strengths
   - Provide answer guidance and talking points

#### Outputs
- **Radar Chart**: 5-dimension scoring visualization (0-10 scale)
- **SWOT Analysis**: 2x2 grid with detailed descriptions
- **Interview Q&A**: 5-10 questions with model answer guides
- **Company Summary**: One-paragraph company positioning
- **Risk/Opportunity Assessment**: What the company is facing right now

#### Data Flow
```
Company Name → News API → Analysis → Scoring → RAG Generation → Q&A Output
```

---

## 3. TECHNICAL REQUIREMENTS

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                       FRONTEND (Streamlit)                   │
│  - Industry Selection | Resume Input | Tab Navigation       │
└────────────┬──────────────────────────────────┬─────────────┘
             │                                  │
        ┌────▼────────────────────┬──────────────▼────┐
        │   BACKEND SERVICES      │   AI/LLM Layer    │
        │  - News Aggregation     │  - Claude API     │
        │  - Data Processing      │  - Trend Extract  │
        │  - Cache Management     │  - Q&A Generate   │
        └────┬────────────────────┴──────────────┬────┘
             │                                   │
        ┌────▼────────────────┬─────────────────▼─────┐
        │   NEWS API LAYER    │   DATABASE/CACHE      │
        │  - NewsAPI.org      │   - Redis (optional)  │
        │  - Naver Search API │   - SQLite (optional) │
        │  - Aggregation      │                       │
        └─────────────────────┴───────────────────────┘
```

### 3.2 News Data Integration

#### Option A: NewsAPI.org (Primary)
- **Endpoint**: `https://newsapi.org/v2/everything`
- **API Key**: Required (free plan: 100 requests/day)
- **Parameters**:
  - `q`: Industry keywords (e.g., "반도체", "이차전지", "AI")
  - `sortBy`: "publishedAt" (latest first)
  - `language`: "ko" (Korean articles)
  - `from`: Date 365 days ago
  - `to`: Today

- **Response Fields Used**:
  ```json
  {
    "title": "Article title",
    "description": "Summary",
    "content": "Full content (truncated)",
    "url": "Source URL",
    "urlToImage": "Thumbnail",
    "publishedAt": "2026-02-16T10:00:00Z",
    "source": {"name": "Source name"},
    "author": "Author name"
  }
  ```

#### Option B: Naver Search API (Secondary/Backup)
- **Endpoint**: `https://openapi.naver.com/v1/search/news.json`
- **Requirements**: 
  - Naver Developer registration
  - Client ID + Client Secret
- **Advantage**: Korean content optimized
- **Rate Limit**: 25,000/day

#### Data Freshness Strategy
- **Cache Duration**: 24 hours for industry data, 48 hours for company data
- **Update Trigger**: Manual refresh button in UI
- **Fallback**: If API fails, serve cached data with "last updated" timestamp

### 3.3 NLP & Analysis Pipeline

#### Trend Extraction
```python
# Pseudo-code
trends = extract_trends(
    news_articles=articles,
    top_n=3,
    method="tf-idf + clustering"
)
# Output: ["Trend 1 summary", "Trend 2 summary", "Trend 3 summary"]
```

#### Keyword Classification
```python
# Pseudo-code
keywords = classify_keywords(
    text=articles,
    categories=["tech", "corp", "policy"],
    weight_factor="frequency * semantic_importance"
)
# Output: [{"word": "HBM3E", "type": "tech", "weight": 95}, ...]
```

#### Sentiment Analysis
```python
# Pseudo-code
sentiments = analyze_sentiment(
    articles_by_month=monthly_articles,
    metrics=["sentiment_score", "intensity", "issue_summary"]
)
# Output: [{"month": "2025-01", "intensity": 8, "score": 9, "issue": "..."}, ...]
```

### 3.4 LLM Integration (Claude 3.5 Sonnet)

#### Use Case 1: Trend Summarization
- **Prompt**: Summarize industry trends from news articles into 3 key insights
- **Input**: List of news articles (title + content)
- **Output**: 3 trend summaries (1-2 sentences each)

#### Use Case 2: SWOT Analysis
- **Prompt**: Based on company news, generate SWOT analysis
- **Input**: Company name + 20-30 recent news articles
- **Output**: JSON with S/W/O/T paragraphs

#### Use Case 3: Interview Q&A Generation
- **Prompt**: Generate interview questions combining company challenges and user strengths
- **Input**: Company news context + Resume/CV
- **Output**: JSON with question + answer guide

#### API Configuration
```python
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 2000,
  "temperature": 0.7,
  "timeout": 30
}
```

---

## 4. DATA STRUCTURE DEFINITIONS (JSON Schema)

### 4.1 Industry Data Structure

```json
{
  "industry": "반도체",
  "period": {
    "from": "2025-02-16",
    "to": "2026-02-16"
  },
  "trends": [
    "2025년 HBM(고대역폭메모리) 수요 급증으로 삼성·SK하이닉스의 생산 경쟁 심화",
    "AI 칩셋 초고성능화 경쟁 속 TSMC와 삼성파운드리의 공정 미세화 기술 경쟁 가속",
    "정부의 '반도체 자급율 상향' 정책 추진으로 국내 제조업 지원책 확대"
  ],
  "keywords": [
    {
      "word": "HBM3E",
      "type": "tech",
      "weight": 95,
      "articles_count": 127
    },
    {
      "word": "삼성전자",
      "type": "corp",
      "weight": 90,
      "articles_count": 203
    },
    {
      "word": "보조금법",
      "type": "policy",
      "weight": 80,
      "articles_count": 42
    },
    {
      "word": "AI칩",
      "type": "tech",
      "weight": 88,
      "articles_count": 156
    },
    {
      "word": "TSMC",
      "type": "corp",
      "weight": 85,
      "articles_count": 98
    }
  ],
  "monthly_sentiment": [
    {
      "month": "2025-01",
      "intensity": 8,
      "score": 8.5,
      "issue": "HBM 수요 급증 및 공급 부족 우려"
    },
    {
      "month": "2025-02",
      "intensity": 7,
      "score": 7.2,
      "issue": "메모리 칩 가격 상승세"
    },
    {
      "month": "2025-03",
      "intensity": 9,
      "score": 8.8,
      "issue": "정부 반도체 지원정책 발표"
    }
  ],
  "source_stats": {
    "total_articles": 1200,
    "date_range_days": 365,
    "top_sources": ["연합뉴스", "이데일리", "테크크런치코리아"],
    "last_updated": "2026-02-16T10:30:00Z"
  }
}
```

### 4.2 Company Analysis Structure

```json
{
  "company": "삼성전자",
  "industry": "반도체",
  "analysis_date": "2026-02-16",
  "company_info": {
    "description": "삼성전자는 메모리반도체와 파운드리 사업을 주도하는 글로벌 반도체 업체",
    "market_cap": "300조원",
    "employees": 267000
  },
  "radar_chart": {
    "labels": ["성장성", "안정성", "혁신성", "ESG", "시장점유율"],
    "scores": [8, 7, 9, 6, 8]
  },
  "swot": {
    "strengths": "HBM3E 기술 리더십, 강력한 R&D 투자, 글로벌 마케팅 네트워크",
    "weaknesses": "높은 제조 비용, ESG 규제 대응 부담, 메모리칩 경기 의존성",
    "opportunities": "AI 칩셋 수요 증가, 파운드리 사업 확대, 정부 반도체 지원정책",
    "threats": "TSMC와의 공정 기술 격차, 중국 저가 경쟁, 지정학적 무역 갈등"
  },
  "recent_news_themes": [
    "HBM3E 양산 확대로 메모리 사업 경쟁력 강화",
    "파운드리 공정 미세화(3nm 이하) 기술 개발 진행",
    "ESG 경영 강화로 탄소중립 목표 수정",
    "미국 정부 반도체 지원금 수령 계획"
  ],
  "interview_qna": [
    {
      "question": "삼성전자가 현재 직면한 HBM3E 공급 경쟁에서, 당신의 [배경/경험]이 어떻게 기여할 수 있을까요?",
      "context": "삼성은 HBM3E 시장에서 수요는 많지만 공급 차질이 발생 중임",
      "guide": "기술적 우수성, 빠른 품질 문제 해결, 팀 협업 능력을 강조. 구체적 프로젝트 사례 준비.",
      "difficulty": "hard"
    },
    {
      "question": "파운드리 사업에서 TSMC를 따라잡기 위해 당신은 어떤 전략을 제안하시겠습니까?",
      "context": "삼성파운드리는 TSMC 대비 기술/비용 경쟁력에서 뒤처짐",
      "guide": "산업 트렌드 이해 + 혁신 역량 표현. 사실 기반의 경쟁 분석 포함.",
      "difficulty": "hard"
    },
    {
      "question": "ESG 경영이 반도체 제조업의 이윤과 충돌할 때, 당신의 의사결정은?",
      "context": "삼성은 ESG 강화 중이지만 제조비용 상승 부담",
      "guide": "윤리적 가치 + 비즈니스 실용성 균형 표현. 구체적 사례 제시.",
      "difficulty": "medium"
    },
    {
      "question": "지정학적 무역 갈등 속에서 삼성의 글로벌 공급망을 어떻게 재구성하겠습니까?",
      "context": "US-China 기술 격리로 삼성의 해외 투자 전략 변화 필요",
      "guide": "위험 요인 인식 + 시나리오 기반 대응안 제시. 국제 정책 이해 필요.",
      "difficulty": "hard"
    },
    {
      "question": "당신이 입사 후 첫 6개월간 달성하고 싶은 마일스톤은 무엇입니까?",
      "context": "삼성의 성장 전략(HBM, 파운드리, ESG)과 연결되는 개별 역할 명확화 필요",
      "guide": "회사 전략과 개인 목표의 정렬 표현. 측정 가능한 성과 지표 제시.",
      "difficulty": "medium"
    }
  ],
  "risk_assessment": {
    "critical_risks": ["TSMC 기술 격차 확대", "메모리칩 가격 하락"],
    "growth_opportunities": ["AI 칩셋 수요", "파운드리 시장 확대"],
    "recommended_focus": "HBM3E 공급 안정화 및 파운드리 기술 혁신에 집중"
  },
  "news_sources": [
    {
      "title": "삼성전자, HBM3E 양산 체제 돌입",
      "date": "2026-02-15",
      "source": "연합뉴스"
    },
    {
      "title": "TSMC 대비 파운드리 기술격차 2년 이상",
      "date": "2026-02-10",
      "source": "매일경제"
    }
  ]
}
```

---

## 5. API INTEGRATION PLAN

### 5.1 News Data Sources

#### Primary: NewsAPI.org
```
API Endpoint: https://newsapi.org/v2/everything
Method: GET

Parameters:
- q: "반도체" OR "삼성전자" (customizable by industry/company)
- language: "ko"
- sortBy: "publishedAt"
- from: "{date_365_days_ago}"
- to: "{today}"
- pageSize: 100
- apiKey: {API_KEY}

Rate Limit: 100 requests/day (free), 500+ (paid)
Response Time: ~2-5 seconds per request
Cost: Free (with limiting), $45/month (99k/month)
```

**Implementation Notes:**
- Implement request caching to respect rate limits
- Handle 429 (Too Many Requests) gracefully
- Retry logic with exponential backoff

#### Secondary: Naver Search API
```
API Endpoint: https://openapi.naver.com/v1/search/news.json
Method: GET

Parameters:
- query: "반도체" OR "삼성전자"
- sort: "date" (최신순)
- start: 1
- display: 100
- Headers:
  - X-Naver-Client-Id: {CLIENT_ID}
  - X-Naver-Client-Secret: {CLIENT_SECRET}

Rate Limit: 25,000 requests/day
Response Time: ~1-2 seconds
Cost: Free

Response Fields:
- title
- link
- description
- pubDate
```

**Backup Strategy:**
```python
def get_news(query: str, source: str = "newsapi"):
    try:
        return news_api_client.search(query)
    except RateLimitError:
        return naver_api_client.search(query)
    except Exception:
        return cache.get_cached_news(query)
```

### 5.2 LLM Integration (Claude)

```python
# Configuration
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# System prompts for different tasks
SYSTEM_PROMPTS = {
    "trend_extraction": """당신은 산업 분석가입니다. 뉴스 기사들을 분석하여 3개의 주요 트렌드를 추출하세요.
    각 트렌드는 구체적이고 기업/업계에 미치는 영향을 명확하게 설명해야 합니다.
    한국어로 답변해주세요.""",
    
    "keyword_extraction": """당신은 NLP 전문가입니다. 주어진 텍스트에서 중요한 키워드를 추출하고 다음 중 하나로 분류하세요:
    - tech: 기술, 혁신, 제품
    - corp: 기업, 사람, 조직
    - policy: 정책, 법규, 규제
    
    JSON 형식으로 반환하세요: [{"word": "...", "type": "...", "weight": 0-100}]""",
    
    "swot_analysis": """당신은 경영 전략 컨설턴트입니다. 제공된 기업 뉴스를 기반으로 SWOT 분석을 수행하세요.
    각 항목(Strengths, Weaknesses, Opportunities, Threats)을 2-3개의 구체적인 예시로 작성하세요.
    JSON 형식으로 반환하세요.""",
    
    "interview_qna": """당신은 취업 코칭 전문가입니다. 기업의 뉴스와 지원자의 이력서를 바탕으로 
    면접 킬러 질문 5개를 생성하세요. 각 질문은 회사의 현재 도전과제와 지원자의 강점을 결합해야 합니다.
    JSON 형식으로 반환하세요."""
}

# API calls
def call_claude(task: str, content: str, system_prompt: str) -> str:
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": content}
        ]
    )
    return message.content[0].text
```

### 5.3 Caching Strategy

```python
# Redis cache (optional, for production)
# SQLite cache (for development/fallback)

CACHE_CONFIG = {
    "industry_data": {
        "ttl": 86400,  # 24 hours
        "key_pattern": "industry:{industry}"
    },
    "company_data": {
        "ttl": 172800,  # 48 hours
        "key_pattern": "company:{company}:{date}"
    },
    "news_articles": {
        "ttl": 43200,  # 12 hours
        "key_pattern": "news:{query}:{date}"
    }
}
```

---

## 6. TECH STACK

| Layer               | Technology             | Purpose                           |
| ------------------- | ---------------------- | --------------------------------- |
| **Frontend**        | Streamlit              | Interactive UI/Dashboard          |
| **Visualization**   | Plotly                 | Charts (Heatmap, Radar)           |
| **NLP/Wordcloud**   | WordCloud, spaCy/NLTK  | Keyword extraction, visualization |
| **LLM**             | Claude 3.5 Sonnet      | Trend/SWOT/Q&A generation         |
| **Backend API**     | FastAPI (optional)     | For scaling                       |
| **Data Processing** | Pandas, NumPy          | Data manipulation                 |
| **News Source**     | NewsAPI.org, Naver API | Real-time news data               |
| **Cache**           | SQLite / Redis         | Data caching                      |
| **Environment**     | Python 3.10+, Poetry   | Dependency management             |

---

## 7. PROJECT STRUCTURE

```
newstrackers-server/
├── pyproject.toml
├── SPEC.md                      # This file
├── README.md
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py                  # Streamlit app entry point
│   ├── config.py                # Configuration
│   ├── cache/
│   │   ├── __init__.py
│   │   └── cache_manager.py     # Caching logic
│   ├── services/
│   │   ├── __init__.py
│   │   ├── news_service.py      # News API integration
│   │   ├── nlp_service.py       # NLP/keyword extraction
│   │   └── llm_service.py       # Claude API calls
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── industry_analyzer.py # Industry trend analysis
│   │   └── company_analyzer.py  # Company/interview analysis
│   ├── visualization/
│   │   ├── __init__.py
│   │   ├── wordcloud_viz.py     # Custom WordCloud
│   │   └── plotly_viz.py        # Plotly charts
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── data_models.py       # Pydantic models
│   └── utils/
│       ├── __init__.py
│       └── helpers.py            # Helper functions
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Pytest fixtures
│   ├── unit/
│   │   ├── test_news_service.py
│   │   ├── test_nlp_service.py
│   │   └── test_llm_service.py
│   ├── integration/
│   │   ├── test_api_integration.py
│   │   └── test_pipeline.py
│   └── e2e/
│       └── test_workflows.py
├── data/
│   ├── fonts/
│   │   └── NanumGothic.ttf       # Korean font for WordCloud
│   └── sample_resumes/           # Test resumes
└── docs/
    ├── API.md                    # API documentation
    ├── DEPLOYMENT.md             # Deployment guide
    └── USER_GUIDE.md             # User manual
```

---

## 8. IMPLEMENTATION ROADMAP

### Phase 1: Core Infrastructure (Week 1)
- [ ] Setup project structure and dependencies
- [ ] Create configuration and environment setup
- [ ] Implement news service with API integration (NewsAPI.org primary, Naver secondary)
- [ ] Create cache manager (SQLite)
- [ ] Setup error handling and logging

### Phase 2: Backend Services (Week 2)
- [ ] Implement NLP service (keyword extraction, sentiment analysis)
- [ ] Implement LLM service (Claude integration)
- [ ] Create data models (Pydantic schemas)
- [ ] Build industry analyzer
- [ ] Build company analyzer

### Phase 3: Frontend & Visualization (Week 3)
- [ ] Create Streamlit app structure
- [ ] Implement industry analysis UI
- [ ] Implement company interview prep UI
- [ ] Create custom WordCloud visualization
- [ ] Create Plotly charts (Heatmap, Radar)

### Phase 4: Testing & Optimization (Week 4)
- [ ] Write unit tests for all services
- [ ] Write integration tests for API pipeline
- [ ] Write E2E tests for user workflows
- [ ] Performance optimization
- [ ] Documentation completion

---

## 9. TESTING STRATEGY

### 9.1 Unit Tests
- **News Service**: Mock API responses, test data parsing, cache operations
- **NLP Service**: Test keyword extraction, sentiment scoring
- **LLM Service**: Mock Claude responses, test prompt formatting
- **Analysis Modules**: Test data transformations, scoring logic

### 9.2 Integration Tests
- **API Pipeline**: Real API calls (limited, with mocking fallback)
- **Data Flow**: News → Processing → Analysis → Output
- **Cache Integration**: Test cache hit/miss scenarios
- **Error Handling**: Test fallback strategies

### 9.3 End-to-End Tests
- **Industry Analysis Workflow**: Full feature from industry selection to visualization
- **Company Interview Preparation**: Full feature from company/resume input to Q&A output
- **UI Interactions**: Streamlit component testing

### 9.4 Test Coverage Target
- Overall: 85%+
- Critical paths (API, LLM, Analysis): 95%+

### 9.5 Test Data
- Real news API responses (stored as fixtures)
- Sample resumes (5-10 variations)
- Sample companies (5-10 major corporations)
- Mock Claude responses for deterministic testing

---

## 10. ERROR HANDLING & RESILIENCE

### Error Scenarios

| Scenario              | Handling                       | Fallback                            |
| --------------------- | ------------------------------ | ----------------------------------- |
| News API Rate Limited | Retry with exponential backoff | Use cached data                     |
| News API Down         | 5s timeout, then fallback      | Cached news + "last updated" notice |
| Claude API Error      | Retry up to 3 times            | Simplified response without LLM     |
| Invalid Resume Input  | Validation error message       | Allow proceed with empty context    |
| Empty News Results    | Inform user                    | Show "no articles found"            |

---

## 11. PERFORMANCE REQUIREMENTS

| Metric                      | Target       |
| --------------------------- | ------------ |
| Industry analysis load time | < 5 seconds  |
| Company analysis load time  | < 5 seconds  |
| News API response           | < 3 seconds  |
| LLM response (Q&A gen)      | < 10 seconds |
| WordCloud generation        | < 2 seconds  |
| Heatmap rendering           | < 1 second   |
| First paint                 | < 2 seconds  |

---

## 12. CONFIGURATION & ENVIRONMENT

### Environment Variables
```
# News APIs
NEWSAPI_KEY=your_key_here
NAVER_CLIENT_ID=your_id_here
NAVER_CLIENT_SECRET=your_secret_here

# LLM
ANTHROPIC_API_KEY=your_key_here

# Cache
CACHE_TYPE=sqlite  # or redis
CACHE_TTL=86400

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
```

---

## 13. SUCCESS CRITERIA

- [ ] News APIs successfully return Korean articles for industries
- [ ] Keyword extraction accurately classifies tech/corp/policy
- [ ] WordCloud renders with proper Korean character support
- [ ] Sentiment heatmap shows meaningful monthly trends
- [ ] Claude-generated interview questions are contextual and challenging
- [ ] SWOT analysis reflects actual company news
- [ ] All tests pass with 85%+ coverage
- [ ] App runs without errors for 5 different industry/company combinations
- [ ] User can complete full workflow in < 2 minutes

---

## 14. NEXT STEPS

1. **Review & Approval**: Review this SPEC document
2. **Setup**: Initialize project structure and dependencies
3. **API Keys**: Obtain NewsAPI.org and Claude API keys
4. **Development**: Follow implementation roadmap in Phase order
5. **Testing**: Run tests after each phase
6. **Deployment**: Prepare for production deployment

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-16  
**Author**: AI Development Team
