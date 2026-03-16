"""LLM 기반 클라이언트 — Claude API 직접 호출 레이어.

모든 LLM 서비스 클래스의 기반. Claude Sonnet 기본, 필요 시 다른 모델 지정 가능.
"""

import json
import logging
import re
from typing import Any, Generator, Optional

from anthropic import Anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Claude API 호출 기반 클래스.

    직접 인스턴스화하거나 서비스 클래스의 베이스로 상속해 사용.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required. Set it in .env or pass api_key to constructor."
            )
        self.client = Anthropic(api_key=self.api_key, max_retries=0)
        self.model = settings.LLM_MODEL
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.temperature = settings.LLM_TEMPERATURE
        self.timeout = settings.LLM_TIMEOUT

    def _call_model(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float = 0.3,
        timeout: Optional[float] = None,
    ) -> str:
        """지정 모델로 Claude API 호출."""
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            timeout=timeout or self.timeout,
        )
        return response.content[0].text

    def _call_claude(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """기본 모델(Sonnet)로 Claude API 호출."""
        try:
            return self._call_model(
                model=self.model,
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature if temperature is not None else self.temperature,
            )
        except Exception as e:
            logger.error("Claude API error: %s", e)
            raise

    @staticmethod
    def _extract_json(response_text: str) -> Any:
        """마크다운 펜스 제거 + JSON 파싱."""
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        # 앞뒤 설명 문구가 있으면 첫 번째 JSON 객체/배열만 추출
        if not (text.startswith("{") or text.startswith("[")):
            start = text.find("{")
            arr_start = text.find("[")
            if start == -1 or (arr_start != -1 and arr_start < start):
                start = arr_start
            if start != -1:
                text = text[start:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            fixed = re.sub(r",\s*([}\]])", r"\1", text)
            return json.loads(fixed)

    def stream_text(
        self,
        system_prompt: str,
        user_message: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Generator[str, None, None]:
        """Claude 응답을 token-by-token 스트리밍."""
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature if temperature is not None else self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                yield from stream.text_stream
        except Exception as e:
            logger.error("Claude streaming error: %s", e)
            raise
