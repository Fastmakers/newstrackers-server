"""리포트 파이프라인 — PDF 텍스트 → ReportResponse 오케스트레이션.

Pipeline steps:
    1. analyze_resume                                      (Haiku, 자소서 구조화)
    2. transform_query(skills, experience_keywords, ...)   (Haiku, 쿼리 3개 생성)
    3. multi_hybrid_search(queries × 3 병렬 → RRF)        (DB, 뉴스 검색)
    4. generate_swot_list || generate_relevance_analysis   (Sonnet, 병렬)
    5. generate_final_report                               (Sonnet)
    6. ReportResponse 조립
"""

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional

from app.schemas.data_models import MatchedNewsItem, ReportResponse, ResumeProfile, SWOTList
from app.services.news_service import NewsService
from app.services.report_generator import ReportGenerator
from app.services.resume_analyzer import ResumeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class ReportInput:
    """파이프라인 입력 파라미터."""

    resume_text: str
    company: str = ""
    job_title: str = ""
    industry: str = ""
    career_level: str = "신입"  # "신입" | "경력"


class ReportPipeline:
    """취업 전략 리포트 파이프라인."""

    def __init__(
        self,
        news_service: NewsService,
        resume_analyzer: ResumeAnalyzer,
        report_generator: ReportGenerator,
    ):
        self._news = news_service
        self._resume = resume_analyzer
        self._report = report_generator

    # ------------------------------------------------------------------
    # 공유 헬퍼
    # ------------------------------------------------------------------

    def _build_matched_news(self, chunks: list) -> list[MatchedNewsItem]:
        result: list[MatchedNewsItem] = []
        for chunk in chunks:
            article = chunk.article
            if article is None:
                continue
            result.append(MatchedNewsItem(
                id=article.id,
                title=article.title,
                job_category=article.category_l2 or "",
                published_at=article.published_at,
                url=article.article_url or "",
                distance=float(getattr(chunk, "distance", 0.0) or 0.0),
            ))
        return result

    def _assemble(
        self,
        resume_profile: ResumeProfile,
        matched_news: list[MatchedNewsItem],
        swot_dict: dict,
        relevance_analysis: str,
        final_report: str,
    ) -> ReportResponse:
        return ReportResponse(
            resume_profile=resume_profile,
            matched_news=matched_news,
            matched_news_count=len(matched_news),
            relevance_analysis=relevance_analysis,
            swot=SWOTList(
                strengths=swot_dict.get("strengths", []),
                weaknesses=swot_dict.get("weaknesses", []),
                opportunities=swot_dict.get("opportunities", []),
                threats=swot_dict.get("threats", []),
            ),
            final_report=final_report,
        )

    # ------------------------------------------------------------------
    # 비동기 실행 (단계별 progress 콜백) — Worker 전용
    # ------------------------------------------------------------------

    async def run_with_progress(
        self,
        inp: ReportInput,
        on_step: Optional[Callable[[int, int, dict], Awaitable[None]]] = None,
    ) -> ReportResponse:
        """비동기 파이프라인 실행. 각 단계 완료 후 on_step(step, pct, partial_data) 콜백 호출."""
        loop = asyncio.get_running_loop()

        # Step 1: analyze_resume — 자소서 구조화 (skills, experience_keywords 추출)
        raw_resume = await loop.run_in_executor(
            None, self._resume.analyze_resume, inp.resume_text
        )
        resolved_job_title = inp.job_title or raw_resume.get("target_role") or ""
        resolved_company   = inp.company  or raw_resume.get("target_company") or ""
        resolved_industry  = inp.industry or raw_resume.get("target_industry") or ""
        resume_profile = ResumeProfile(
            company=resolved_company,
            job_title=resolved_job_title,
            industry=resolved_industry,
            skills=raw_resume.get("skills") or [],
            experiences=raw_resume.get("experience_keywords") or [],
        )
        if on_step:
            await on_step(1, 20, {"resume_profile": resume_profile.model_dump(mode="json")})

        # Step 2: transform_query + HyDE 병렬 실행
        # transform_query: 구조화된 역량 데이터로 뉴스 검색 쿼리 3개 생성
        # generate_hyde_docs: 가상 뉴스 기사 2개 생성 (HyDE — 벡터 공간 정합도 향상)
        transformed, hyde_docs = await asyncio.gather(
            loop.run_in_executor(
                None,
                functools.partial(
                    self._resume.transform_query,
                    resolved_company, resolved_job_title, resolved_industry,
                    raw_resume.get("skills") or [],
                    raw_resume.get("experience_keywords") or [],
                    raw_resume.get("search_keywords") or [],
                    inp.resume_text[:600],
                ),
            ),
            loop.run_in_executor(
                None,
                functools.partial(
                    self._resume.generate_hyde_docs,
                    resolved_company, resolved_job_title, resolved_industry,
                    raw_resume.get("search_keywords") or [],
                    inp.resume_text[:600],
                ),
            ),
        )
        fallback_query = f"{resolved_company} {resolved_job_title} 산업 동향".strip() or "최신 산업 동향"
        queries: list[str] = transformed.get("queries") or [fallback_query]
        # HyDE 문서를 쿼리 리스트에 추가 (최대 2개) — 벡터 검색 정합도 향상
        all_queries = queries + (hyde_docs or [])
        logger.debug("검색 쿼리 %d개 (transform: %d, HyDE: %d)", len(all_queries), len(queries), len(hyde_docs or []))

        # Step 3: multi_hybrid_search — 쿼리(3+2)개 병렬 검색 후 RRF 합산 (top_k*2 후보)
        # keyword_query: 회사명 단독 사용 (pg_trgm은 복합어 사용 시 무관 기사 매칭됨)
        chunks = await loop.run_in_executor(
            None,
            functools.partial(
                self._news.multi_hybrid_search,
                queries=all_queries, keyword_query=resolved_company, top_k=30,
            ),
        )

        # Step 3.5: Cross-Encoder 재랭킹 — RRF 30개 후보 → 자소서 관련도 순 top 15
        # query: 회사명 + 직무 + 자소서 발췌 → Cross-Encoder가 (query, 기사) 쌍 직접 비교
        rerank_query = f"{resolved_company} {resolved_job_title}\n{inp.resume_text}"
        chunks = await loop.run_in_executor(
            None,
            functools.partial(
                self._news.rerank_chunks,
                rerank_query, chunks, 15,
            ),
        )

        matched_news = self._build_matched_news(chunks)
        if on_step:
            await on_step(3, 50, {"matched_news": [n.model_dump(mode="json") for n in matched_news]})

        # Step 4: SWOT + relevance (병렬)
        swot_dict, relevance_analysis = await asyncio.gather(
            loop.run_in_executor(None, functools.partial(
                self._report.generate_swot_list,
                inp.resume_text, resolved_company, resolved_job_title,
                chunks, resolved_industry, inp.career_level,
            )),
            loop.run_in_executor(None, functools.partial(
                self._report.generate_relevance_analysis,
                inp.resume_text, chunks, resolved_company,
                resolved_industry, resolved_job_title, inp.career_level,
            )),
        )
        if on_step:
            await on_step(4, 80, {"swot": swot_dict, "relevance_analysis": relevance_analysis})

        # Step 5: final report
        final_report = await loop.run_in_executor(
            None,
            functools.partial(
                self._report.generate_final_report,
                resume=inp.resume_text, company=resolved_company,
                job_title=resolved_job_title, industry=resolved_industry,
                swot=swot_dict, relevance_analysis=relevance_analysis,
                career_level=inp.career_level,
            ),
        )
        if on_step:
            await on_step(5, 100, {"final_report": final_report})

        return self._assemble(resume_profile, matched_news, swot_dict, relevance_analysis, final_report)
