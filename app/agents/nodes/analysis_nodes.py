"""
Analysis nodes - heuristic (non-LLM) computations.
These are pure functions: they take state and return a partial state update.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime

from app.agents.state import CompanyState, IndustryState
from app.schemas.data_models import (
    CompanyInfo,
    MonthlySentiment,
    RadarChart,
    RiskAssessment,
    SourceStats,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Industry analysis nodes
# ============================================================================


def compute_monthly_sentiment(state: IndustryState) -> dict:
    """Compute monthly sentiment scores from article keywords (heuristic)."""
    articles = state.get("articles", [])
    logger.info(f"[analysis] Computing monthly sentiment ({len(articles)} articles)")

    monthly_data: dict = {}
    positive_words = ["성장", "증가", "확대", "강화", "개선", "혁신", "성공", "달성"]
    negative_words = ["하락", "감소", "위기", "악화", "문제", "도전", "어려움", "손실"]

    for article in articles:
        try:
            if not article.published_at:
                continue
            month_key = article.published_at.strftime("%Y-%m")  # YYYY-MM

            if month_key not in monthly_data:
                monthly_data[month_key] = {"count": 0, "positive": 0, "negative": 0, "keywords": []}

            monthly_data[month_key]["count"] += 1
            text = f"{article.title} {article.content[:200]}".lower()

            if any(word in text for word in positive_words):
                monthly_data[month_key]["positive"] += 1
            if any(word in text for word in negative_words):
                monthly_data[month_key]["negative"] += 1

            monthly_data[month_key]["keywords"].extend(
                [t.title() for t in article.title.split() if len(t) > 2]
            )
        except Exception as e:
            logger.warning(f"[analysis] Error processing article for sentiment: {e}")

    sentiments = []
    for month_key in sorted(monthly_data.keys())[-12:]:
        data = monthly_data[month_key]
        total = data["count"]
        positive_ratio = data["positive"] / total if total > 0 else 0
        negative_ratio = data["negative"] / total if total > 0 else 0

        score = 5 + (positive_ratio - negative_ratio) * 5
        score = max(0, min(10, score))
        intensity = min(10, max(1, total // 2))

        top_keywords = Counter(data["keywords"]).most_common(3)
        issue = ", ".join([k[0] for k in top_keywords]) if top_keywords else "뉴스 추적 중"

        sentiments.append(MonthlySentiment(
            month=month_key,
            intensity=intensity,
            score=round(score, 1),
            issue=issue,
        ))

    logger.info(f"[analysis] Monthly sentiment computed for {len(sentiments)} months")
    return {"monthly_sentiment": sentiments}


def compute_source_stats(state: IndustryState) -> dict:
    """Compute statistics about news sources."""
    articles = state.get("articles", [])
    days_back = state.get("days_back", 365)
    logger.info(f"[analysis] Computing source stats ({len(articles)} articles)")

    sources = Counter([a.source for a in articles if a.source])
    stats = SourceStats(
        total_articles=len(articles),
        date_range_days=days_back,
        top_sources=[source for source, _ in sources.most_common(5)],
        last_updated=datetime.now(),
    )
    return {"source_stats": stats}


# ============================================================================
# Company analysis nodes
# ============================================================================


def extract_company_info(state: CompanyState) -> dict:
    """Extract basic company description from articles."""
    articles = state.get("articles", [])
    company = state["company"]
    logger.info(f"[analysis] Extracting company info for '{company}'")

    snippets = [a.content[:200] for a in articles[:5] if a.content]
    description = snippets[0] if snippets else f"{company}에 대한 정보가 제한적입니다."

    info = CompanyInfo(description=description, market_cap=None, employees=None)
    return {"company_info": info}


def score_five_dimensions(state: CompanyState) -> dict:
    """Score company on 5 dimensions based on news keyword frequency (heuristic)."""
    articles = state.get("articles", [])
    company = state["company"]
    logger.info(f"[analysis] Scoring 5 dimensions for '{company}'")

    text = " ".join([
        f"{a.title} {a.content[:200]}" for a in articles[:20]
    ]).lower()

    dimension_keywords = [
        ["성장", "매출", "증수", "확대", "상장", "시장 점유율"],       # 성장성
        ["안정", "일관", "지속", "신뢰", "신용등급", "건전성"],        # 안정성
        ["혁신", "기술", "R&D", "개발", "특허", "2세대"],              # 혁신성
        ["ESG", "환경", "지속가능", "사회", "윤리", "탄소중립"],       # ESG
        ["점유율", "시장", "지위", "경쟁", "리더", "선두"],            # 시장점유율
    ]

    def score(keywords: list, max_score: float = 10.0) -> float:
        count = sum(text.count(kw) for kw in keywords)
        raw = min(max_score, (count / 5.0) * max_score)
        base = max_score * 0.5
        variance = (count % 3) * 0.5
        return round(min(max_score, base + raw + variance - max_score * 0.3), 1)

    scores = [max(1.0, min(9.0, score(kws))) for kws in dimension_keywords]
    return {"radar_chart": RadarChart(scores=scores)}


def extract_news_themes(state: CompanyState) -> dict:
    """Extract main themes from recent article titles (3-word sliding window)."""
    articles = state.get("articles", [])
    logger.info(f"[analysis] Extracting news themes ({len(articles)} articles)")

    themes = []
    for article in articles[:10]:
        words = article.title.split()
        for i in range(len(words) - 2):
            phrase = " ".join(words[i : i + 3])
            if len(phrase) > 5:
                themes.append(phrase)

    top_themes = [t for t, _ in Counter(themes).most_common(4)]
    return {"news_themes": top_themes if top_themes else ["뉴스 분석 중"]}


def assess_risks(state: CompanyState) -> dict:
    """Generate risk and opportunity assessment from article keywords (heuristic)."""
    articles = state.get("articles", [])
    company = state["company"]
    logger.info(f"[analysis] Assessing risks for '{company}'")

    text = " ".join([
        f"{a.title} {a.content[:200]}" for a in articles[:15]
    ]).lower()

    risk_keywords = {
        "규제 리스크": ["규제", "제재", "조사"],
        "시장 변화": ["하락", "감소", "경쟁"],
        "기술 리스크": ["구식", "교체", "위협"],
        "공급망 리스크": ["공급", "부족", "중단"],
    }
    opportunity_keywords = {
        "AI/기술": ["AI", "머신러닝", "자동화", "데이터"],
        "시장 확대": ["신시장", "해외", "확장"],
        "혁신 제품": ["신상품", "출시", "개발"],
        "파트너십": ["협력", "제휴", "인수"],
    }

    critical_risks = [r for r, kws in risk_keywords.items() if any(kw in text for kw in kws)]
    growth_opportunities = [o for o, kws in opportunity_keywords.items() if any(kw in text for kw in kws)]

    recommended_focus = (
        f"{company}의 성공을 위해 "
        f"{'기술 혁신' if growth_opportunities else '시장 안정성'} 중심의 전략이 필요합니다."
    )

    risk = RiskAssessment(
        critical_risks=critical_risks[:3] or ["기본 시장 리스크"],
        growth_opportunities=growth_opportunities[:3] or ["지속적 성장"],
        recommended_focus=recommended_focus,
    )
    return {"risk_assessment": risk}
