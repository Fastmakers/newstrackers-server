import anthropic
from openai import AsyncOpenAI

from app.core.config import settings


class ClaudeLLMService:
    """LLM 기반 뉴스 분석 서비스 (OpenAI 우선, Anthropic 폴백)"""

    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None
        self._openai_client: AsyncOpenAI | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    @property
    def openai_client(self) -> AsyncOpenAI:
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """
        LLM 텍스트 생성.
        기본은 OpenAI를 사용하고, 실패 시 Anthropic 키가 있으면 폴백합니다.
        """
        try:
            response = await self.openai_client.chat.completions.create(
                model=settings.OPENAI_CHAT_MODEL,
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("OpenAI 응답 본문이 비어 있습니다.")
            return content.strip()
        except Exception:
            if not settings.ANTHROPIC_API_KEY:
                raise

            message = await self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text_blocks = [
                block.text
                for block in message.content
                if getattr(block, "type", None) == "text" and getattr(block, "text", None)
            ]
            if not text_blocks:
                raise ValueError("Anthropic 응답 본문이 비어 있습니다.")
            return "\n".join(text_blocks).strip()

    async def summarize_news(self, title: str, content: str, industry: str) -> str:
        """
        뉴스 기사를 요약합니다.

        Args:
            title: 기사 제목
            content: 기사 본문
            industry: 산업 카테고리

        Returns:
            요약된 텍스트 (3~5문장)
        """
        prompt = (
            f"다음은 '{industry}' 산업 관련 뉴스 기사입니다. "
            f"핵심 내용을 3~5문장으로 한국어로 요약해주세요.\n\n"
            f"제목: {title}\n\n본문: {content}"
        )
        return await self.complete(prompt, max_tokens=500)

    async def analyze_industry_trends(self, news_texts: list[str], industry: str) -> str:
        """
        산업군별 뉴스 트렌드를 분석합니다.

        Args:
            news_texts: 뉴스 본문 리스트
            industry: 산업 카테고리

        Returns:
            트렌드 분석 결과
        """
        combined = "\n---\n".join(news_texts[:20])
        prompt = (
            f"다음은 '{industry}' 산업 관련 최근 뉴스 모음입니다. "
            f"주요 트렌드와 핵심 이슈를 분석하여 한국어로 정리해주세요.\n\n"
            f"뉴스 목록:\n{combined}"
        )
        return await self.complete(prompt, max_tokens=1000)


# 싱글톤 인스턴스
claude_llm_service = ClaudeLLMService()
