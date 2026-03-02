"""
Pydantic data models for the application
Defines all request/response schemas
"""

from datetime import datetime
from typing import List, Optional

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
    date_range_days: int
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
    days_back: int = Field(default=365, ge=1, le=365)


class CompanyAnalysisRequest(BaseModel):
    """Request for company analysis"""
    company: str
    industry: str
    resume: str = Field(..., min_length=10)
    days_back: int = Field(default=365, ge=1, le=365)


# ============================================================================
# Search Models
# ============================================================================

class SearchRequest(BaseModel):
    """하이브리드 뉴스 검색 요청."""
    query: str = Field(..., min_length=1, description="검색어 또는 자소서 원문")
    category_l2: Optional[str] = Field(None, description="카테고리 필터 (예: 경제, IT·과학)")
    top_k: int = Field(default=10, ge=1, le=50, description="반환할 결과 수")
    transform_query: bool = Field(
        default=True,
        description="True면 Claude Haiku로 쿼리를 핵심 키워드+문장으로 압축 후 검색",
    )


class SearchResult(BaseModel):
    """검색 결과 단건."""
    rank: int
    article_id: int
    chunk_no: int
    title: str
    published_at: Optional[datetime] = None
    category_l2: Optional[str] = None
    chunk_text: str
    rrf_score: Optional[float] = None   # 디버깅용 RRF 점수


class SearchResponse(BaseModel):
    """하이브리드 검색 응답."""
    original_query: str
    transformed_query: Optional[str] = None   # 질의 변환 후 실제 검색 쿼리
    keywords: List[str] = Field(default_factory=list)  # 추출된 핵심 키워드
    results: List[SearchResult]
    total_results: int
    search_time_ms: float


# ============================================================================
# Response Models
# ============================================================================

class APIResponse(BaseModel):
    """Generic API response"""
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthCheck(BaseModel):
    """Health check response"""
    status: str
    services: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
