"""
Fetch nodes - retrieve news articles from the DB.
"""

from __future__ import annotations

import logging

from app.agents.state import CompanyState, IndustryState
from app.services.news_service import NewsService

logger = logging.getLogger(__name__)


def make_fetch_industry_articles(news_service: NewsService):
    """Node factory: fetch articles for industry analysis."""

    def fetch_articles(state: IndustryState) -> dict:
        industry = state["industry"]
        logger.info(f"[fetch] Fetching articles for industry: {industry}")
        articles = news_service.get_articles(industry)
        logger.info(f"[fetch] Retrieved {len(articles)} articles")
        return {"articles": articles}

    return fetch_articles


def make_fetch_company_articles(news_service: NewsService):
    """Node factory: fetch articles for company analysis.

    Falls back to industry articles if no company-specific articles found.
    """

    def fetch_articles(state: CompanyState) -> dict:
        company = state["company"]
        industry = state["industry"]

        logger.info(f"[fetch] Fetching articles for company: {company}")
        articles = news_service.get_articles(company)

        if not articles:
            logger.warning(f"[fetch] No articles for {company}, falling back to industry: {industry}")
            articles = news_service.get_articles(industry)

        logger.info(f"[fetch] Retrieved {len(articles)} articles")
        return {"articles": articles}

    return fetch_articles
