"""
LangGraph state definitions for industry and company analysis graphs.
"""

from __future__ import annotations

from typing import List, Optional

from typing_extensions import TypedDict

from app.schemas.data_models import (
    CompanyAnalysis,
    CompanyInfo,
    IndustryData,
    InterviewQNA,
    Keyword,
    MonthlySentiment,
    NewsArticle,
    RadarChart,
    ResumeAnalysis,
    RiskAssessment,
    SourceStats,
    SWOT,
)


class IndustryState(TypedDict, total=False):
    """State for the industry analysis graph.

    Required inputs: industry, days_back
    Built up by nodes: articles, trends, keywords, monthly_sentiment, source_stats
    Final output: result
    """

    # Inputs (set at graph invocation)
    industry: str
    days_back: int

    # Intermediate state (set by nodes)
    articles: List[NewsArticle]
    trends: List[str]
    keywords: List[Keyword]
    monthly_sentiment: List[MonthlySentiment]
    source_stats: Optional[SourceStats]

    # Final output (set by assemble_result)
    result: Optional[IndustryData]


class CompanyState(TypedDict, total=False):
    """State for the company analysis graph.

    Required inputs: company, industry, resume, days_back
    Built up by nodes: articles, company_info, radar_chart, swot, etc.
    Final output: result
    """

    # Inputs (set at graph invocation)
    company: str
    industry: str
    resume: str
    days_back: int

    # Intermediate state (set by nodes)
    articles: List[NewsArticle]
    resume_analysis: Optional[ResumeAnalysis]
    company_info: Optional[CompanyInfo]
    radar_chart: Optional[RadarChart]
    swot: Optional[SWOT]
    news_themes: List[str]
    interview_qna: List[InterviewQNA]
    risk_assessment: Optional[RiskAssessment]

    # Final output (set by assemble_result)
    result: Optional[CompanyAnalysis]
