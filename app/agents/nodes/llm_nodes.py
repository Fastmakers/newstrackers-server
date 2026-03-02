"""
LLM nodes - call the LLM service for trend/keyword/SWOT/interview generation.
All nodes are factories that close over an LLMService instance.
"""

from __future__ import annotations

import logging

from app.agents.state import CompanyState, IndustryState
from app.schemas.data_models import InterviewQNA, Keyword, ResumeAnalysis, SWOT
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def make_extract_trends_node(llm_service: LLMService):
    """Node factory: extract 3 industry trends via LLM."""

    def extract_trends(state: IndustryState) -> dict:
        articles = state.get("articles", [])
        industry = state["industry"]
        logger.info(f"[llm] Extracting trends for '{industry}' ({len(articles)} articles)")
        trends = llm_service.extract_trends(articles, industry)
        logger.info(f"[llm] Extracted {len(trends)} trends")
        return {"trends": trends}

    return extract_trends


def make_extract_keywords_node(llm_service: LLMService):
    """Node factory: extract top keywords via LLM."""

    def extract_keywords(state: IndustryState) -> dict:
        articles = state.get("articles", [])
        logger.info(f"[llm] Extracting keywords ({len(articles)} articles)")
        keywords_list = llm_service.extract_keywords(articles, top_n=10)
        keywords = [Keyword(**kw) for kw in keywords_list]
        logger.info(f"[llm] Extracted {len(keywords)} keywords")
        return {"keywords": keywords}

    return extract_keywords


def make_generate_swot_node(llm_service: LLMService):
    """Node factory: generate SWOT analysis via LLM."""

    def generate_swot(state: CompanyState) -> dict:
        company = state["company"]
        articles = state.get("articles", [])
        logger.info(f"[llm] Generating SWOT for '{company}'")
        try:
            swot_dict = llm_service.generate_swot_analysis(company, articles)
            swot = SWOT(
                strengths=swot_dict.get("strengths", ""),
                weaknesses=swot_dict.get("weaknesses", ""),
                opportunities=swot_dict.get("opportunities", ""),
                threats=swot_dict.get("threats", ""),
            )
        except Exception as e:
            logger.error(f"[llm] SWOT generation failed: {e}")
            swot = SWOT(
                strengths="분석 실패",
                weaknesses="분석 실패",
                opportunities="분석 실패",
                threats="분석 실패",
            )
        return {"swot": swot}

    return generate_swot


def make_analyze_resume_node(llm_service: LLMService):
    """Node factory: extract structured info from resume text via LLM."""

    def analyze_resume(state: CompanyState) -> dict:
        resume = state.get("resume", "")
        logger.info("[llm] Analyzing resume")
        raw = llm_service.analyze_resume(resume)
        if not isinstance(raw, dict):
            raw = {}

        def _str_list(val) -> list:
            return [s for s in (val or []) if isinstance(s, str)]

        target_role = raw.get("target_role")
        resume_analysis = ResumeAnalysis(
            skills=_str_list(raw.get("skills")),
            experience_keywords=_str_list(raw.get("experience_keywords")),
            target_role=target_role if isinstance(target_role, str) else None,
            strengths=_str_list(raw.get("strengths")),
            search_keywords=_str_list(raw.get("search_keywords")),
        )
        logger.info(
            f"[llm] Resume analysis: role={resume_analysis.target_role}, "
            f"skills={resume_analysis.skills[:3]}"
        )
        return {"resume_analysis": resume_analysis}

    return analyze_resume


def make_generate_interview_questions_node(llm_service: LLMService):
    """Node factory: generate interview Q&A via LLM.

    Uses resume_analysis (from analyze_resume node) to personalize questions.
    """

    def generate_interview_questions(state: CompanyState) -> dict:
        company = state["company"]
        resume = state.get("resume", "")
        articles = state.get("articles", [])
        resume_analysis = state.get("resume_analysis")

        # Enrich resume context with structured analysis if available
        resume_context = resume
        if resume_analysis:
            enriched = (
                f"[분석 요약] 핵심 스킬: {', '.join(resume_analysis.skills[:5])} | "
                f"강점: {', '.join(resume_analysis.strengths[:3])} | "
                f"희망 직무: {resume_analysis.target_role or '미정'}\n\n"
                f"{resume}"
            )
            resume_context = enriched

        logger.info(f"[llm] Generating interview questions for '{company}'")
        try:
            qnas = llm_service.generate_interview_questions(
                company, resume_context, articles, num_questions=5
            )
            interview_qna = [InterviewQNA(**qna) for qna in qnas]
        except Exception as e:
            logger.error(f"[llm] Interview question generation failed: {e}")
            interview_qna = [
                InterviewQNA(
                    question=f"{company}에 지원하게 된 동기는 무엇인가요?",
                    context="기본 동기 파악",
                    guide=(
                        "회사의 비전, 기술, 문화에 대한 이해를 바탕으로"
                        " 구체적인 이유를 제시하세요."
                    ),
                    difficulty="easy",
                )
            ]
        logger.info(f"[llm] Generated {len(interview_qna)} interview questions")
        return {"interview_qna": interview_qna}

    return generate_interview_questions
