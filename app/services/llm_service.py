"""LLM 서비스 — 검색/분석 엔드포인트용 Claude 서비스.

LLMClient를 상속해 기반 호출 능력을 제공하고,
RAG 검색 답변과 하위 호환 위임 메서드를 포함한다.

하위 호환성(Backward Compatibility):
  analyze_resume, transform_query, generate_swot_list,
  generate_relevance_analysis, generate_final_report 는 각 전용 서비스에 위임한다.
  기존 엔드포인트/테스트 코드를 변경하지 않아도 동작한다.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.services.llm_client import LLMClient
from app.services.report_generator import ReportGenerator
from app.services.resume_analyzer import ResumeAnalyzer

logger = logging.getLogger(__name__)


class LLMService(LLMClient):
    """검색 엔드포인트 서비스 + 하위 호환 파사드.

    - generate_rag_answer: search.py에서 직접 사용
    - 나머지 report 메서드: ResumeAnalyzer/ReportGenerator에 위임
    """

    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        self._resume_analyzer = ResumeAnalyzer(api_key=api_key)
        self._report_generator = ReportGenerator(api_key=api_key)

    # ------------------------------------------------------------------
    # 위임 — ResumeAnalyzer
    # ------------------------------------------------------------------

    def analyze_resume(self, resume: str) -> Dict[str, Any]:
        return self._resume_analyzer.analyze_resume(resume)

    def transform_query(self, text: str) -> Dict[str, Any]:
        return self._resume_analyzer.transform_query(text)

    # ------------------------------------------------------------------
    # 위임 — ReportGenerator
    # ------------------------------------------------------------------

    def generate_swot_list(
        self,
        resume: str,
        company: str,
        job_title: str,
        chunks: list,
        industry: str = "",
        career_level: str = "신입",
    ) -> Dict[str, List[str]]:
        return self._report_generator.generate_swot_list(
            resume, company, job_title, chunks, industry, career_level
        )

    def generate_relevance_analysis(
        self,
        resume: str,
        chunks: list,
        company: str = "",
        industry: str = "",
        job_title: str = "",
        career_level: str = "신입",
    ) -> str:
        return self._report_generator.generate_relevance_analysis(
            resume, chunks, company, industry, job_title, career_level
        )

    def generate_final_report(
        self,
        resume: str,
        company: str,
        job_title: str,
        industry: str,
        swot: Dict[str, List[str]],
        relevance_analysis: str = "",
        career_level: str = "신입",
    ) -> str:
        return self._report_generator.generate_final_report(
            resume, company, job_title, industry, swot, relevance_analysis, career_level
        )

    # ------------------------------------------------------------------
    # RAG 검색 답변 생성 (search.py에서 사용)
    # ------------------------------------------------------------------

    def generate_rag_answer(
        self,
        query: str,
        chunks: list,
        resume: str | None = None,
        company: str | None = None,
        position: str | None = None,
    ) -> str:
        """검색된 뉴스 청크를 컨텍스트로 면접 준비 답변 생성 (Claude Sonnet)."""
        if not chunks:
            return "관련 뉴스를 찾을 수 없어 답변을 생성할 수 없습니다."

        context = "\n\n".join(
            f"[{i + 1}] {chunk.chunk_text[:400]}"
            for i, chunk in enumerate(chunks)
        )

        meta_lines = ""
        if company:
            meta_lines += f"지원 기업: {company}\n"
        if position:
            meta_lines += f"지원 직군: {position}\n"

        target = f"{company or '해당 기업'}{f' ({position})' if position else ''}"

        system_prompt = """당신은 취업 면접 코치입니다.
지원자의 자기소개서와 관련 뉴스 기사를 바탕으로, 면접에서 활용할 수 있는
구체적이고 실용적인 인사이트를 제공합니다.
뉴스의 트렌드·이슈를 지원자의 경험·역량과 연결해 답변하세요."""

        user_message = f"""다음 내용을 바탕으로 면접 준비에 도움이 되는 분석을 제공하세요.

{meta_lines}[자기소개서]
{resume[:2000] if resume else query[:500]}

[관련 뉴스 발췌]
{context}

다음 항목을 포함해 답변하세요:
1. {target} 관련 최신 트렌드 요약 (뉴스 기반)
2. 지원자 역량과 트렌드의 연결 포인트
3. 면접에서 활용할 수 있는 구체적 키워드·사례"""

        return self._call_claude(system_prompt, user_message, temperature=0.5)
