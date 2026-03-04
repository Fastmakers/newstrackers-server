"""
Pydantic data models for the application
Defines all request/response schemas
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# News Data Models
# ============================================================================

class NewsArticle(BaseModel):
    """매일경제 뉴스 기사 도메인 모델 (SPEC: docs/SPEC_SEARCH.md §2)"""
    id: int = 0
    title: str
    summary: Optional[str] = None
    body: str = ""
    source_name: Optional[str] = None   # 언론사명 ("매일경제")
    writer: Optional[str] = None        # 기자명 (정규화 후)
    article_url: Optional[str] = None
    category_l1: Optional[str] = None
    category_l2: Optional[str] = None
    category_l3: Optional[str] = None
    published_at: Optional[datetime] = None
    keyword_list: List[str] = Field(default_factory=list)

    # 하위 호환 프로퍼티 (기존 코드가 .content, .source, .category 사용)
    @property
    def content(self) -> str:
        return self.body

    @property
    def source(self) -> Optional[str]:
        return self.source_name

    @property
    def category(self) -> Optional[str]:
        return self.category_l2


class NewsChunk(BaseModel):
    """뉴스 청크 도메인 모델 (SPEC: docs/SPEC_SEARCH.md §2)"""
    id: int
    article_id: int
    chunk_no: int
    chunk_text: str
    chunk_chars: int
    article: Optional[NewsArticle] = None


class Keyword(BaseModel):
    """Individual keyword with metadata"""
    word: str
    type: str = Field(..., pattern="^(tech|corp|policy)$")
    weight: float = Field(..., ge=0, le=100)
    articles_count: Optional[int] = None


class MonthlySentiment(BaseModel):
    """Monthly sentiment data"""
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")  # YYYY-MM format
    intensity: int = Field(..., ge=0, le=10)
    score: float = Field(..., ge=0, le=10)
    issue: str


class SourceStats(BaseModel):
    """Statistics about news sources"""
    total_articles: int
    top_sources: List[str]
    last_updated: datetime


class IndustryData(BaseModel):
    """Industry trend analysis output"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "industry": "반도체",
            "period": {"from": "2025-02-16", "to": "2026-02-16"},
            "trends": ["Trend 1", "Trend 2", "Trend 3"],
            "keywords": [{"word": "HBM3E", "type": "tech", "weight": 95}],
            "monthly_sentiment": [
                {"month": "2025-01", "intensity": 8, "score": 8.5, "issue": "..."}
            ]
        }
    })
    
    industry: str
    period: dict = Field(default_factory=dict)
    trends: List[str] = Field(..., min_length=3, max_length=3)
    keywords: List[Keyword]
    monthly_sentiment: List[MonthlySentiment]
    source_stats: Optional[SourceStats] = None


# ============================================================================
# Company Analysis Models
# ============================================================================

class RadarChart(BaseModel):
    """5-dimension scoring for companies"""
    labels: List[str] = Field(default=[
        "성장성", "안정성", "혁신성", "ESG", "시장점유율"
    ])
    scores: List[float] = Field(..., min_length=5, max_length=5)
    
    def validate_scores(self):
        for score in self.scores:
            if not (0 <= score <= 10):
                raise ValueError(f"Score must be between 0 and 10, got {score}")


class SWOT(BaseModel):
    """SWOT Analysis"""
    strengths: str
    weaknesses: str
    opportunities: str
    threats: str


class InterviewQNA(BaseModel):
    """Interview question and answer guide"""
    question: str
    context: Optional[str] = None
    guide: str
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")


class RiskAssessment(BaseModel):
    """Company risk and opportunity assessment"""
    critical_risks: List[str]
    growth_opportunities: List[str]
    recommended_focus: str


class CompanyNewsArticle(BaseModel):
    """Single news article for company analysis"""
    title: str
    date: str
    source: str


class CompanyInfo(BaseModel):
    """Basic company information"""
    description: str
    market_cap: Optional[str] = None
    employees: Optional[int] = None


class CompanyAnalysis(BaseModel):
    """Company analysis output (for interview preparation)"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "company": "삼성전자",
            "industry": "반도체",
            "analysis_date": "2026-02-16T10:00:00Z",
            "radar_chart": {
                "labels": ["성장성", "안정성", "혁신성", "ESG", "시장점유율"],
                "scores": [8, 7, 9, 6, 8]
            },
            "swot": {
                "strengths": "...",
                "weaknesses": "...",
                "opportunities": "...",
                "threats": "..."
            },
            "interview_qna": [{"question": "...", "guide": "..."}]
        }
    })
    
    company: str
    industry: str
    analysis_date: datetime = Field(default_factory=datetime.now)
    company_info: Optional[CompanyInfo] = None
    radar_chart: RadarChart
    swot: SWOT
    recent_news_themes: List[str]
    interview_qna: List[InterviewQNA]
    risk_assessment: RiskAssessment
    news_sources: Optional[List[CompanyNewsArticle]] = None


# ============================================================================
# Resume Analysis Models
# ============================================================================

class ResumeAnalysis(BaseModel):
    """Structured extraction from a resume / cover letter."""
    skills: List[str] = []
    experience_keywords: List[str] = []
    target_role: Optional[str] = None
    strengths: List[str] = []
    search_keywords: List[str] = []  # Used for semantic article search


# ============================================================================
# Request Models
# ============================================================================

class IndustryAnalysisRequest(BaseModel):
    """Request for industry analysis"""
    industry: str


class CompanyAnalysisRequest(BaseModel):
    """Request for company analysis"""
    company: str
    industry: str
    resume: str = Field(..., min_length=10)


# ============================================================================
# Search Models
# ============================================================================

class SearchRequest(BaseModel):
    """RAG 파이프라인 검색 요청.

    pipeline 선택:
        v1 — 자소서 원문 → 벡터 검색 Top 5 → Claude 답변
        v2 — 자소서 원문 → Haiku 질의변환 → Hybrid(Vector+trgm→RRF) Top 5 → Claude 답변
        v3 — v2 동일 (RRF Top 40) → Cross-Encoder → Top 10 → Claude 답변
    """
    company: str = Field(..., min_length=1, description="지원 기업명 (예: 삼성전자)")
    position: str = Field(..., min_length=1, description="지원 직군 (예: 백엔드 개발자)")
    resume: str = Field(..., min_length=10, description="자소서 원문")
    top_k: int = Field(default=15, ge=1, le=50, description="반환할 결과 수")
    pipeline: Literal["v1", "v2", "v3"] = Field(
        default="v2",
        description="RAG 파이프라인 버전 (v1=Baseline, v2=Hybrid, v3=Reranker)",
    )
    skip_answer: bool = Field(default=False, description="True면 Claude 답변 생성 생략 (검색 결과만 반환)")


class SearchResult(BaseModel):
    """검색 결과 단건."""
    rank: int
    article_id: int
    chunk_no: int
    title: str
    published_at: Optional[datetime] = None
    category_l2: Optional[str] = None
    chunk_text: str


class LatencyBreakdown(BaseModel):
    """파이프라인 단계별 소요 시간 (ms)."""
    query_transform_ms: Optional[float] = None   # v2/v3 — Haiku 질의변환
    retrieval_ms: float                           # 검색 (벡터 or 하이브리드+RRF)
    rerank_ms: Optional[float] = None            # v3 — Cross-Encoder 재배열
    answer_ms: Optional[float] = None            # Claude 답변 생성
    total_ms: float


class SearchResponse(BaseModel):
    """RAG 파이프라인 검색 응답."""
    pipeline: str                                         # 실행된 파이프라인 버전
    transformed_query: Optional[str] = None              # v2/v3 — Haiku가 변환한 쿼리
    keywords: List[str] = Field(default_factory=list)    # v2/v3 — 추출된 핵심 키워드
    results: List[SearchResult]
    total_results: int
    answer: Optional[str] = None                         # Claude가 생성한 RAG 답변
    latency: LatencyBreakdown
