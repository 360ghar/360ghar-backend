"""
ZhipuAI GLM Provider with Vision support.

This module implements the AIProvider interface for ZhipuAI's GLM models,
supporting both text and vision (image) inputs via the GLM-5V-Turbo model.
All HTTP requests use the retry-enabled ``_make_request`` from the base class.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.services.ai.base import (
    AIMessage,
    AIProvider,
    AIProviderError,
    AIRole,
    VisionInput,
)

logger = get_logger(__name__)


class GLMProvider(AIProvider):
    """
    ZhipuAI GLM provider with vision support.

    Supports models like:
    - glm-5v-turbo (vision + coding model, recommended)
    - glm-4.6v-flash (vision model, free tier)
    - glm-4.6v (vision model)
    - glm-4.1v-thinking (vision + reasoning)
    - glm-4.5 (text only)
    - glm-4.6 (text only)
    - glm-4.7 (text only)
    """

    @property
    def name(self) -> str:
        return "ZhipuAI GLM"

    @property
    def supports_vision(self) -> bool:
        m = self.config.model.lower()
        return "4.6v" in m or "5v" in m or "4v" in m or "4.1v" in m

    @property
    def supports_json_mode(self) -> bool:
        return True

    def _get_api_url(self) -> str:
        """Get the API URL from settings or use default."""
        return getattr(settings, "GLM_API_URL", "https://api.z.ai/api/coding/paas/v4/chat/completions")

    def _build_headers(self) -> dict[str, str]:
        """Build common request headers."""
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the messages array for GLM API.

        GLM uses OpenAI-compatible message format with vision support.
        Vision input is attached only to the first user message to avoid
        duplicating the large base64 string.
        """
        result = []
        vision_attached = False

        for msg in messages:
            role = msg.role.value

            if vision_input and msg.role == AIRole.USER and not vision_attached:
                content = [
                    {"type": "text", "text": msg.content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{vision_input.mime_type};base64,{vision_input.image_base64}"
                        }
                    }
                ]
                result.append({"role": role, "content": content})
                vision_attached = True
            else:
                result.append({"role": role, "content": msg.content})

        return result

    async def complete(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
    ) -> str:
        """Generate a text completion from GLM (with automatic retries)."""
        url = self._get_api_url()
        headers = self._build_headers()
        payload = {
            "model": self.config.model,
            "messages": self._build_messages(messages, vision_input),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        client = self._get_http_client()
        t_start = time.monotonic()
        response = await self._make_request(client, url, headers, payload)
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "External call completed",
            extra={"provider": self.name, "model": self.config.model, "duration_ms": round(elapsed_ms, 1), "endpoint": url},
        )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                message=f"API returned invalid JSON response body: {exc}",
                provider=self.name,
            ) from exc

        return self._extract_text_from_response(data)

    async def complete_json(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a structured JSON completion from GLM (with automatic retries)."""
        url = self._get_api_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._build_messages(messages, vision_input),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": json_schema,
                    "strict": True,
                }
            }

        client = self._get_http_client()
        t_start = time.monotonic()
        response = await self._make_request(client, url, headers, payload)
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "External call completed",
            extra={"provider": self.name, "model": self.config.model, "duration_ms": round(elapsed_ms, 1), "endpoint": url, "json_mode": True},
        )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                message=f"API returned invalid JSON response body: {exc}",
                provider=self.name,
            ) from exc

        text = self._extract_text_from_response(data)
        return self._parse_json_response(text)

    def _extract_text_from_response(self, data: dict[str, Any]) -> str:
        """Extract text content from GLM API response (OpenAI-compatible format)."""
        try:
            choices = data.get("choices", [])
            if not choices:
                raise AIProviderError(
                    message="No choices in response",
                    provider=self.name,
                )

            message = choices[0].get("message", {})
            content = message.get("content", "")

            if not content:
                finish_reason = choices[0].get("finish_reason")
                logger.warning(
                    "GLM returned empty content (finish_reason=%s)",
                    finish_reason,
                    extra={"provider": self.name, "finish_reason": finish_reason},
                )
                raise AIProviderError(
                    message=f"No content in response message (finish_reason={finish_reason})",
                    provider=self.name,
                )

            return str(content)

        except (KeyError, IndexError) as e:
            logger.error("Failed to extract text from GLM response: %s", e)
            raise AIProviderError(
                message=f"Invalid response structure: {e}",
                provider=self.name,
            ) from e
