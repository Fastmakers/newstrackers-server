"""자소서 분석 서비스 — Claude Haiku 기반 빠른 분석."""

import logging
from typing import Any, Dict

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
{resume[:2000]}

응답 형식 (JSON):
{{
  "skills": ["기술 스킬1", "기술 스킬2"],
  "experience_keywords": ["경험 키워드1", "경험 키워드2"],
  "target_role": "희망 직무 (없으면 null)",
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

    def transform_query(self, text: str) -> Dict[str, Any]:
        """자소서/검색어 → 핵심 키워드 + 압축 검색 쿼리 (Claude Haiku).

        Returns:
            {"keywords": [...], "query": "압축된 검색 문장"}
        """
        system_prompt = (
            "당신은 뉴스 검색 쿼리 최적화 전문가입니다. "
            "자소서와 지원 정보를 분석해, 경제/산업 뉴스 기사에서 검색할 쿼리를 생성합니다. "
            "반드시 유효한 JSON만 응답하세요. "
            "마크다운 펜스, 설명 텍스트, trailing comma 없이 순수 JSON 객체만 출력하세요."
        )

        user_message = f"""다음 내용을 경제/기업 뉴스 검색 쿼리로 변환하세요.

{text[:1500]}

규칙:
- keywords는 지원 기업의 뉴스에서 등장할 법한 사업/전략/서비스/제품 키워드 (FastAPI, 마이크로서비스 같은 지원자 개인 기술스택 X)
- query는 "[기업명] [사업부문] 전략/사업/서비스" 형태로 작성 (뉴스 제목에 나올 법한 표현)
- query는 15단어 이내로 압축

예시:
- 잘못된 예: "삼성전자 DX부문 FastAPI 마이크로서비스 병렬처리"
- 올바른 예: "삼성전자 DX부문 소프트웨어 AI 갤럭시 서비스 전략"

응답 형식 (JSON):
{{
  "keywords": ["기업명", "사업부문", "사업키워드1", "사업키워드2"],
  "query": "[기업명] [사업부문] 관련 뉴스 키워드 (15단어 이내)"
}}"""

        try:
            raw = self._call_model(_HAIKU, system_prompt, user_message, max_tokens=300, temperature=0.2, timeout=10)
            try:
                return self._extract_json(raw)
            except Exception as json_err:
                logger.warning("transform_query JSON 파싱 실패: %s\nRAW:\n%s", json_err, raw)
                return {"keywords": [], "query": text}
        except Exception as e:
            logger.warning("Query transformation failed, using original: %s", e)
            return {"keywords": [], "query": text}
