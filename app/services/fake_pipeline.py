"""Fake services for architecture-only async worker experiments.

These services intentionally avoid:
    - Anthropic / OpenAI calls
    - vector search / real article DB queries

They preserve the same ReportPipeline shape so the experiment isolates:
    API process topology vs worker topology
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.schemas.data_models import NewsArticle, NewsChunk


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _extract_resume_keywords(text: str, limit: int = 4) -> list[str]:
    words = []
    seen: set[str] = set()
    for raw in text.replace("\n", " ").split():
        cleaned = raw.strip(".,()[]{}<>\"' ")
        if len(cleaned) < 2:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        words.append(cleaned)
        if len(words) >= limit:
            break
    return words or ["Python", "FastAPI", "협업", "문제해결"]


class FakeResumeAnalyzer:
    def analyze_resume(self, resume: str) -> dict:
        _sleep(settings.FAKE_RESUME_DELAY_SEC)
        keywords = _extract_resume_keywords(resume, limit=4)
        return {
            "skills": keywords[:3],
            "experience_keywords": keywords[:4],
            "target_role": "실험용 백엔드 개발자",
            "strengths": ["빠른 학습", "협업", "문제 해결"],
            "search_keywords": keywords,
        }

    def transform_query(self, text: str) -> dict:
        _sleep(settings.FAKE_QUERY_DELAY_SEC)
        keywords = _extract_resume_keywords(text, limit=4)
        return {
            "keywords": keywords,
            "query": " ".join(keywords[:3]),
        }


class FakeNewsService:
    def hybrid_search(
        self,
        query: str,
        keyword_query: str | None = None,
        category_l2: str | None = None,
        top_k: int = 5,
    ) -> list[NewsChunk]:
        _sleep(settings.FAKE_SEARCH_DELAY_SEC)
        total = min(top_k, max(1, settings.FAKE_MATCHED_NEWS_COUNT))
        now = datetime.now(timezone.utc)
        results: list[NewsChunk] = []
        for index in range(total):
            article_id = 10_000 + index
            article = NewsArticle(
                id=article_id,
                title=f"[Fake] {keyword_query or query} 실험 기사 {index + 1}",
                body=f"실험용 본문 {index + 1}. query={query}",
                source_name="FakeNews",
                category_l2=category_l2 or "실험",
                published_at=now - timedelta(days=index),
                article_url=f"https://fake.local/news/{article_id}",
            )
            results.append(
                NewsChunk(
                    id=article_id,
                    article_id=article_id,
                    chunk_no=0,
                    chunk_text=f"실험용 뉴스 청크 {index + 1}. {query}",
                    chunk_chars=len(query) + 20,
                    article=article,
                    distance=round(0.05 + index * 0.03, 3),
                )
            )
        return results


class FakeReportGenerator:
    def generate_swot_list(
        self,
        resume: str,
        company: str,
        job_title: str,
        chunks: list,
        industry: str = "",
        career_level: str = "신입",
    ) -> dict:
        _sleep(settings.FAKE_SWOT_DELAY_SEC)
        role = job_title or "실험 직무"
        company_name = company or "실험 기업"
        return {
            "strengths": [f"{company_name} {role} 대응력", "빠른 적응력"],
            "weaknesses": ["도메인 지식 보완 필요"],
            "opportunities": [f"{industry or '실험 산업'} 이슈를 빠르게 학습 가능"],
            "threats": [f"{career_level} 경쟁 심화"],
        }

    def generate_relevance_analysis(
        self,
        resume: str,
        chunks: list,
        company: str = "",
        industry: str = "",
        job_title: str = "",
        career_level: str = "신입",
    ) -> str:
        _sleep(settings.FAKE_RELEVANCE_DELAY_SEC)
        return (
            "### 산업 트렌드 요약\n"
            f"- {industry or '실험 산업'} 관련 기사 흐름을 추적 중입니다.\n"
            "- 구조 비교 실험을 위해 고정 응답을 반환합니다.\n"
            "- 외부 AI 지연 대신 일정한 분석 지연만 반영합니다.\n\n"
            "### 역량-트렌드 연결 포인트\n"
            f"- **{job_title or '실험 직무'}** — 구조 비교에 집중할 수 있도록 고정 결과를 제공합니다.\n"
            "- **협업** — API/worker 분리 여부가 응답성에 주는 영향을 보기 좋습니다.\n"
            "- **문제해결** — 외부 의존성 없이 병목을 분리할 수 있습니다.\n\n"
            "### 면접 활용 키워드\n"
            "- **queue_wait**: worker pickup 지연을 확인하세요.\n"
            "- **processing_time**: 실제 처리 시간을 확인하세요.\n"
            "- **lead_time**: 최종 사용자 체감 시간을 확인하세요."
        )

    def generate_final_report(
        self,
        resume: str,
        company: str,
        job_title: str,
        industry: str,
        swot: dict,
        relevance_analysis: str = "",
        career_level: str = "신입",
    ) -> str:
        _sleep(settings.FAKE_FINAL_REPORT_DELAY_SEC)
        return (
            "## 면접 준비 포인트\n\n"
            f"### Q1. {company or '실험 기업'} 지원 동기를 어떻게 설명할 것인가?\n"
            "외부 AI 없이도 구조 비교가 가능하도록 고정 질문을 사용합니다.\n"
            "**핵심 답변 방향:** 시스템 구조 차이와 본인 강점을 연결해 설명합니다.\n\n"
            f"### Q2. {job_title or '실험 직무'} 적합성을 어떻게 보여줄 것인가?\n"
            "고정된 실험 데이터로도 답변 구조는 충분히 검증 가능합니다.\n"
            "**핵심 답변 방향:** 경험 요약과 문제 해결 과정을 짧게 정리합니다.\n\n"
            "### Q3. 비동기 구조의 장단점을 어떻게 판단할 것인가?\n"
            "실험 지표를 근거로 설명합니다.\n"
            "**핵심 답변 방향:** queue wait, processing, lead time 순으로 말합니다.\n\n"
            "---\n\n"
            "## 최종 권고사항\n\n"
            "### 핵심 준비 사항\n"
            "1. **지표 비교** — p50/p95를 함께 보세요.\n"
            "2. **동일 조건 유지** — 입력 PDF와 job 수를 고정하세요.\n"
            "3. **로그 확인** — worker dispatch/completed 로그를 같이 보세요.\n\n"
            "### 차별화 전략\n"
            "외부 AI를 제거한 상태에서 구조 차이만 검증한 뒤, 마지막에 실서비스 의존성을 다시 붙여 2차 검증을 진행하세요."
        )
