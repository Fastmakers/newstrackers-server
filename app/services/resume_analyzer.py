"""자소서 분석 서비스 — Claude Haiku 기반 빠른 분석."""

import logging
from typing import Any, Dict, List

from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5-20251001"


class ResumeAnalyzer(LLMClient):
    """자소서 구조화 분석 + 검색 쿼리 최적화 (Claude Haiku 사용)."""

    def analyze_resume(self, resume: str) -> Dict[str, Any]:
        """자소서/이력서에서 핵심 정보 추출.

        Returns:
            {"skills": [...], "experience_keywords": [...], "target_role": ...,
             "strengths": [...], "search_keywords": [...]}
        """
        if not resume or not resume.strip():
            return {
                "skills": [], "experience_keywords": [],
                "target_role": None, "strengths": [], "search_keywords": [],
            }

        system_prompt = (
            "당신은 채용 전문가입니다. 자기소개서나 이력서를 분석하여 "
            "지원자의 핵심 정보를 구조화합니다. "
            "반드시 유효한 JSON만 응답하세요. 설명 텍스트, 마크다운 펜스, 주석, "
            "trailing comma 없이 순수 JSON 객체만 출력하세요."
        )

        user_message = f"""다음 자기소개서/이력서를 분석하여 핵심 정보를 추출하세요.

            이력서/자기소개서:
            {resume}

            응답 형식 (JSON):
            {{
            "skills": ["기술 스킬1", "기술 스킬2"],
            "experience_keywords": ["경험 키워드1", "경험 키워드2"],
            "target_role": "희망 직무 (없으면 null)",
            "target_company": "지원 또는 희망 기업명 (언급 없으면 null)",
            "target_industry": "희망 산업 분야 (예: IT·전자, 금융, 제조 등 / 언급 없으면 null)",
            "strengths": ["강점1", "강점2"],
            "search_keywords": ["관련 뉴스 검색에 유용한 산업/기술 키워드1", "키워드2"]
            }}"""

        try:
            raw = self._call_model(_HAIKU, system_prompt, user_message, max_tokens=1024, temperature=0.3, timeout=15)
            try:
                return self._extract_json(raw)
            except Exception as json_err:
                logger.error("analyze_resume JSON 파싱 실패: %s\nRAW:\n%s", json_err, raw)
                return {
                    "skills": [], "experience_keywords": [],
                    "target_role": None, "strengths": [], "search_keywords": [],
                }
        except Exception as e:
            logger.error("Resume analysis failed: %s", e)
            return {
                "skills": [], "experience_keywords": [],
                "target_role": None, "strengths": [], "search_keywords": [],
            }

    def transform_query(
        self,
        company: str,
        job_title: str,
        industry: str,
        skills: List[str],
        experience_keywords: List[str],
    ) -> Dict[str, List[str]]:
        """analyze_resume 구조화 결과 → 기업·직무 연관 뉴스 검색 쿼리 3개 생성 (Claude Haiku).

        Args:
            company:              지원 기업명
            job_title:            지원 직무
            industry:             산업 분류
            skills:               analyze_resume가 추출한 기술 스킬 목록
            experience_keywords:  analyze_resume가 추출한 경험 키워드 목록

        Returns:
            {"queries": ["쿼리1", "쿼리2", "쿼리3"]}
        """
        system_prompt = (
            "당신은 취업 면접 전문가입니다. "
            "지원자의 역량 정보와 지원 정보를 분석해, "
            "면접관이 물어볼 만한 최신 산업 동향을 다루는 뉴스 기사를 찾기 위한 검색 쿼리를 생성합니다. "
            "반드시 유효한 JSON만 응답하세요. "
            "마크다운 펜스, 설명 텍스트, trailing comma 없이 순수 JSON 객체만 출력하세요."
        )

        skills_str = ", ".join(skills) if skills else "없음"
        experience_str = ", ".join(experience_keywords) if experience_keywords else "없음"

        if company:
            user_message = f"""다음 지원자 역량 정보를 바탕으로, 면접 준비에 필요한 뉴스 검색 쿼리 3개를 생성하세요.

지원 기업: {company}
지원 직무: {job_title}
산업: {industry}
보유 기술: {skills_str}
경험 키워드: {experience_str}

규칙:
- 쿼리 3개는 각각 다른 각도에서 기업+직무 연관 뉴스를 커버해야 합니다
  1. 기업 전략/사업 방향 (예: "{company} AI 사업 전략 2025")
  2. 지원자 도메인 기술이 이 기업/산업에서 어떻게 쓰이는지 (예: "{company} 온디바이스 AI 적용")
  3. 해당 직무와 기업이 교차하는 시장 변화 (예: "{company} {job_title} 디지털 전환")
- 모든 쿼리는 반드시 {company} 또는 {company}의 핵심 사업과 직접 연결되어야 합니다
- FastAPI, CLAHE 같은 구현 기술스택은 쿼리에 쓰지 말고, 그 기술이 속한 산업 도메인으로 변환하세요
- 각 쿼리는 뉴스 제목에 나올 법한 표현으로, 10단어 이내로 작성하세요

응답 형식 (JSON):
{{
  "queries": ["쿼리1", "쿼리2", "쿼리3"]
}}"""
        else:
            industry_hint = f"산업: {industry}\n" if industry else ""
            user_message = f"""다음 지원자 역량 정보를 바탕으로, 산업 동향 파악에 필요한 뉴스 검색 쿼리 3개를 생성하세요.
지원 기업은 미정입니다. 지원자의 역량과 희망 직무·산업에 맞는 최신 트렌드 중심으로 쿼리를 만드세요.

지원 직무: {job_title or "미정"}
{industry_hint}보유 기술: {skills_str}
경험 키워드: {experience_str}

규칙:
- 쿼리 3개는 각각 다른 각도에서 직무·산업 관련 뉴스를 커버해야 합니다
  1. 지원자 도메인의 최신 기술·트렌드 (예: "온디바이스 AI 반도체 시장 동향 2025")
  2. 해당 직무군의 채용·역량 변화 (예: "소프트웨어 엔지니어 AI 역량 요구 증가")
  3. 관련 산업의 시장 변화 또는 주요 이슈 (예: "IT 서비스 클라우드 전환 가속")
- 특정 기업명은 쿼리에 넣지 마세요
- FastAPI, CLAHE 같은 구현 기술스택은 쿼리에 쓰지 말고, 그 기술이 속한 산업 도메인으로 변환하세요
- 각 쿼리는 뉴스 제목에 나올 법한 표현으로, 10단어 이내로 작성하세요

응답 형식 (JSON):
{{
  "queries": ["쿼리1", "쿼리2", "쿼리3"]
}}"""

        try:
            raw = self._call_model(_HAIKU, system_prompt, user_message, max_tokens=300, temperature=0.4, timeout=10)
            try:
                result = self._extract_json(raw)
                queries = result.get("queries") or []
                if not queries:
                    raise ValueError("queries 비어있음")
                return {"queries": queries}
            except Exception as json_err:
                logger.warning("transform_query JSON 파싱 실패: %s\nRAW:\n%s", json_err, raw)
                fallback = f"{company} {job_title} 산업 동향".strip() or "최신 산업 동향"
                return {"queries": [fallback]}
        except Exception as e:
            logger.warning("Query transformation failed, using fallback: %s", e)
            fallback = f"{company} {job_title} 산업 동향".strip() or "최신 산업 동향"
            return {"queries": [fallback]}
