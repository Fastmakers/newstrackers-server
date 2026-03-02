"""
LLM Service - Uses Claude API for analysis tasks
"""

import json
import logging
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from app.core.config import settings
from app.schemas.data_models import NewsArticle

logger = logging.getLogger(__name__)


class LLMService:
    """Service for Claude-based analysis."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required. Set it in .env or pass api_key to constructor."
            )
        self.client = Anthropic(api_key=self.api_key)
        self.model = settings.LLM_MODEL
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.temperature = settings.LLM_TEMPERATURE
        self.timeout = settings.LLM_TIMEOUT

    def _call_claude(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
    ) -> str:
        """Call Claude API with error handling."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=temperature or self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                timeout=self.timeout,
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

    @staticmethod
    def _extract_json(response_text: str) -> Any:
        """Strip markdown fences and parse JSON from LLM response."""
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())

    def extract_trends(
        self,
        articles: List[NewsArticle],
        industry: str,
    ) -> List[str]:
        """Extract industry trends from news articles.

        Returns: List of 3 trend summaries
        """
        if not articles:
            logger.warning("No articles provided for trend extraction")
            return ["데이터 부족으로 분석 불가"] * 3

        article_texts = "\n\n".join([
            f"Title: {a.title}\nContent: {a.content[:300]}\nDate: {a.published_at or ''}"
            for a in articles[:30]
        ])

        system_prompt = """당신은 산업 분석가입니다. 주어진 뉴스 기사들을 분석하여
        산업의 주요 트렌드를 추출하세요. 정확하고 구체적인 인사이트를 제공하세요."""

        user_message = f"""다음 '{industry}' 산업의 뉴스 기사들을 분석하고,
        주요 트렌드 3가지를 불릿 형식으로 정리해주세요. 각 트렌드는 1-2문장으로 작성하세요.

뉴스 기사들:
{article_texts}

응답 형식:
- 트렌드 1: ...
- 트렌드 2: ...
- 트렌드 3: ..."""

        response = self._call_claude(system_prompt, user_message)

        trends = []
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("-"):
                trend = line.lstrip("- ").split(":", 1)[-1].strip()
                if trend:
                    trends.append(trend)

        if len(trends) < 3:
            trends = trends + ["" for _ in range(3 - len(trends))]
        else:
            trends = trends[:3]

        return trends

    def extract_keywords(
        self,
        articles: List[NewsArticle],
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        """Extract and classify keywords from articles."""
        if not articles:
            logger.warning("No articles provided for keyword extraction")
            return []

        article_texts = "\n\n".join([
            f"{a.title} {a.content[:200]}"
            for a in articles[:30]
        ])

        system_prompt = """당신은 NLP 전문가입니다. 주어진 텍스트에서 중요한 키워드를 추출하고
        다음 중 하나로 분류하세요:
        - tech: 기술, 혁신, 제품, R&D
        - corp: 기업명, 조직, 임원, M&A
        - policy: 정책, 법규, 규제, 정부 지원

        JSON 형식으로 응답하세요."""

        user_message = f"""다음 기사들에서 가장 중요한 키워드 {top_n}개를 추출하세요.
        각 키워드는 0-100 사이의 가중치를 할당하세요.

기사 내용:
{article_texts}

응답 형식 (JSON):
[{{"word": "keyword", "type": "tech|corp|policy", "weight": 85}}, ...]"""

        try:
            response = self._call_claude(system_prompt, user_message, temperature=0.3)
            keywords = self._extract_json(response)
            return keywords[:top_n]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse keywords JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Keyword extraction failed: {e}")
            return []

    def generate_swot_analysis(
        self,
        company: str,
        articles: List[NewsArticle],
    ) -> Dict[str, str]:
        """Generate SWOT analysis from company news."""
        if not articles:
            logger.warning(f"No articles provided for SWOT analysis of {company}")
            return {
                "strengths": "정보 부족",
                "weaknesses": "정보 부족",
                "opportunities": "정보 부족",
                "threats": "정보 부족",
            }

        article_texts = "\n\n".join([
            f"[{a.published_at or ''}] {a.title}\n{a.content[:300]}"
            for a in articles[:20]
        ])

        system_prompt = f"""당신은 경영 전략 컨설턴트입니다. {company}의 뉴스를 기반으로
        SWOT 분석을 수행합니다. 각 항목은 구체적이고 actionable한 내용으로 작성하세요."""

        user_message = f"""{company}의 최근 뉴스를 기반으로 SWOT 분석을 작성하세요.
        각 항목(Strengths, Weaknesses, Opportunities, Threats)은 2-3개의 구체적인 예시를 포함하되,
        한국어로 작성하세요.

뉴스:
{article_texts}

응답 형식 (JSON):
{{
  "strengths": "강점 내용...",
  "weaknesses": "약점 내용...",
  "opportunities": "기회 내용...",
  "threats": "위협 내용..."
}}"""

        try:
            response = self._call_claude(system_prompt, user_message, temperature=0.5)
            return self._extract_json(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse SWOT JSON: {e}")
            return {
                "strengths": "분석 실패",
                "weaknesses": "분석 실패",
                "opportunities": "분석 실패",
                "threats": "분석 실패",
            }
        except Exception as e:
            logger.error(f"SWOT analysis failed: {e}")
            return {}

    def generate_interview_questions(
        self,
        company: str,
        resume: str,
        articles: List[NewsArticle],
        num_questions: int = 5,
    ) -> List[Dict[str, str]]:
        """Generate interview questions combining company challenges and candidate strengths."""
        if not articles:
            logger.warning(f"No articles provided for interview questions for {company}")
            return []

        article_texts = "\n\n".join([
            f"[{a.published_at or ''}] {a.title}\n{a.content[:300]}"
            for a in articles[:15]
        ])

        system_prompt = f"""당신은 경력개발 전문가이자 면접 코칭 전문가입니다.
{company}의 뉴스와 지원자의 이력서를 기반으로 깊이 있는 면접 질문을 생성합니다.
질문은 회사의 현재 도전과제와 지원자의 강점을 결합하여 만들어야 합니다."""

        user_message = f"""다음 정보를 바탕으로 면접 킬러 질문 {num_questions}개를 생성하세요.
각 질문은 회사의 현재 상황과 지원자의 경험을 연결하는 고차원적 질문이어야 합니다.

회사: {company}

최근 뉴스:
{article_texts}

지원자 이력서:
{resume[:500]}...

응답 형식 (JSON):
[
  {{
    "question": "면접 질문...",
    "context": "질문 背景...",
    "guide": "답변 가이드...",
    "difficulty": "easy|medium|hard"
  }},
  ...
]"""

        try:
            response = self._call_claude(system_prompt, user_message, temperature=0.7)
            qnas = self._extract_json(response)
            return qnas[:num_questions]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse interview questions JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Interview question generation failed: {e}")
            return []

    def transform_query(self, text: str) -> Dict[str, Any]:
        """자소서/검색어 → 핵심 키워드 + 압축 검색 쿼리 (Claude Haiku 사용).

        긴 자소서나 복잡한 검색어를 뉴스 검색에 최적화된 짧은 쿼리로 압축한다.
        빠른 응답을 위해 Haiku 모델을 사용한다.

        Returns:
            {"keywords": [...], "query": "압축된 검색 문장"}
        """
        system_prompt = """당신은 검색 쿼리 최적화 전문가입니다.
주어진 텍스트에서 뉴스 기사 검색에 가장 유용한 핵심 키워드와 압축 쿼리를 추출합니다.
반드시 JSON 형식으로만 응답하세요."""

        user_message = f"""다음 텍스트를 뉴스 검색에 최적화된 쿼리로 변환하세요.

텍스트:
{text[:1500]}

응답 형식 (JSON):
{{
  "keywords": ["핵심키워드1", "핵심키워드2", "핵심키워드3"],
  "query": "뉴스 검색에 최적화된 압축 쿼리 (1~2문장)"
}}"""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                temperature=0.2,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                timeout=10,
            )
            return self._extract_json(response.content[0].text)
        except Exception as e:
            logger.warning("Query transformation failed, using original: %s", e)
            return {"keywords": [], "query": text}

    def stream_text(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
    ):
        """Claude 응답을 token-by-token으로 스트리밍 (Generator[str]).

        SSE 엔드포인트에서 사용: StreamingResponse(event_stream(), ...)
        """
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=temperature or self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                yield from stream.text_stream
        except Exception as e:
            logger.error("Claude streaming error: %s", e)
            raise

    def stream_industry_trends(
        self,
        articles: List[NewsArticle],
        industry: str,
    ):
        """산업 트렌드 분석 스트리밍 Generator.

        Yields: str (Claude 응답 텍스트 chunk)
        """
        if not articles:
            yield f"'{industry}' 관련 기사가 없어 분석을 수행할 수 없습니다."
            return

        article_texts = "\n\n".join([
            f"Title: {a.title}\nContent: {a.content[:300]}\nDate: {a.published_at or ''}"
            for a in articles[:30]
        ])

        system_prompt = """당신은 산업 분석가입니다. 주어진 뉴스 기사들을 분석하여
        산업의 주요 트렌드를 추출하세요. 정확하고 구체적인 인사이트를 제공하세요."""

        user_message = f"""다음 '{industry}' 산업의 뉴스 기사들을 분석하고,
        주요 트렌드 3가지를 불릿 형식으로 정리해주세요. 각 트렌드는 1-2문장으로 작성하세요.

뉴스 기사들:
{article_texts}

응답 형식:
- 트렌드 1: ...
- 트렌드 2: ...
- 트렌드 3: ..."""

        yield from self.stream_text(system_prompt, user_message)

    def stream_swot(
        self,
        company: str,
        articles: List[NewsArticle],
    ):
        """SWOT 분석 스트리밍 Generator.

        Yields: str (Claude 응답 텍스트 chunk)
        """
        if not articles:
            yield f"'{company}' 관련 기사가 없어 SWOT 분석을 수행할 수 없습니다."
            return

        article_texts = "\n\n".join([
            f"[{a.published_at or ''}] {a.title}\n{a.content[:300]}"
            for a in articles[:20]
        ])

        system_prompt = f"""당신은 경영 전략 컨설턴트입니다. {company}의 뉴스를 기반으로
        SWOT 분석을 수행합니다. 각 항목은 구체적이고 actionable한 내용으로 작성하세요."""

        user_message = f"""{company}의 최근 뉴스를 기반으로 SWOT 분석을 작성하세요.
        각 항목(Strengths, Weaknesses, Opportunities, Threats)은 2-3개의 구체적인 예시를 포함하되,
        한국어로 작성하세요.

뉴스:
{article_texts}"""

        yield from self.stream_text(system_prompt, user_message, temperature=0.5)

    def analyze_resume(self, resume: str) -> Dict[str, Any]:
        """Extract structured information from a resume or cover letter.

        Returns skills, experience keywords, target role, strengths,
        and search_keywords for semantic article retrieval.
        """
        if not resume or not resume.strip():
            return {
                "skills": [], "experience_keywords": [],
                "target_role": None, "strengths": [], "search_keywords": [],
            }

        system_prompt = """당신은 채용 전문가입니다. 자기소개서나 이력서를 분석하여
        지원자의 핵심 정보를 구조화합니다. JSON 형식으로만 응답하세요."""

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
            response = self._call_claude(system_prompt, user_message, temperature=0.3)
            return self._extract_json(response)
        except Exception as e:
            logger.error(f"Resume analysis failed: {e}")
            return {
                "skills": [], "experience_keywords": [],
                "target_role": None, "strengths": [], "search_keywords": [],
            }
