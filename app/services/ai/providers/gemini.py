"""
Google Gemini AI Provider with Vision support.

This module implements the AIProvider interface for Google's Gemini models,
supporting both text and vision (image) inputs.
All HTTP requests use the retry-enabled ``_make_request`` from the base class.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.logging import get_logger
from app.services.ai.base import (
    AIMessage,
    AIProvider,
    AIProviderError,
    AIRole,
    VisionInput,
)

logger = get_logger(__name__)


class GeminiProvider(AIProvider):
    """
    Google Gemini AI provider with vision support.

    Supports models like:
    - gemini-3.1-flash-lite-preview (recommended, vision + fast)
    """

    API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def name(self) -> str:
        return "Google Gemini"

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_json_mode(self) -> bool:
        return True

    def _build_url(self, action: str = "generateContent") -> str:
        """Build the API URL for the configured model."""
        return f"{self.API_BASE_URL}/{self.config.model}:{action}?key={self.config.api_key}"

    def _build_contents(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the contents array for Gemini API.

        Gemini uses a different format than OpenAI-style APIs:
        - System messages go into system_instruction
        - User/Assistant messages go into contents
        """
        contents = []
        vision_attached = False

        for msg in messages:
            if msg.role == AIRole.SYSTEM:
                continue

            role = "user" if msg.role == AIRole.USER else "model"
            parts: list[dict[str, Any]] = []

            if msg.content:
                parts.append({"text": msg.content})

            # Attach vision input only to the first user message to avoid
            # duplicating the large base64 string across multiple parts.
            if vision_input and msg.role == AIRole.USER and not vision_attached:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": vision_input.mime_type,
                            "data": vision_input.image_base64,
                        }
                    }
                )
                vision_attached = True

            if parts:
                contents.append({"role": role, "parts": parts})

        return contents

    def _extract_system_instruction(self, messages: list[AIMessage]) -> str | None:
        """Extract system instruction from messages."""
        for msg in messages:
            if msg.role == AIRole.SYSTEM:
                return msg.content
        return None

    def _build_generation_config(self, json_mode: bool = False) -> dict[str, Any]:
        """Build generation configuration."""
        config: dict[str, Any] = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_tokens,
        }
        if json_mode:
            config["responseMimeType"] = "application/json"
        return config

    async def complete(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
    ) -> str:
        """Generate a text completion from Gemini (with automatic retries)."""
        url = self._build_url()
        payload: dict[str, Any] = {
            "contents": self._build_contents(messages, vision_input),
            "generationConfig": self._build_generation_config(json_mode=False),
        }

        system_instruction = self._extract_system_instruction(messages)
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        client = self._get_http_client()
        headers: dict[str, str] = {"Content-Type": "application/json"}
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
        """Generate a structured JSON completion from Gemini (with automatic retries)."""
        url = self._build_url()
        payload: dict[str, Any] = {
            "contents": self._build_contents(messages, vision_input),
            "generationConfig": self._build_generation_config(json_mode=True),
        }

        system_instruction = self._extract_system_instruction(messages)
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        client = self._get_http_client()
        headers: dict[str, str] = {"Content-Type": "application/json"}
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
        """Extract text content from Gemini API response."""
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                raise AIProviderError(
                    message="No candidates in response",
                    provider=self.name,
                )

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            if not parts:
                raise AIProviderError(
                    message="No parts in response content",
                    provider=self.name,
                )

            text_parts = [part.get("text", "") for part in parts if "text" in part]
            return "".join(text_parts)

        except (KeyError, IndexError) as e:
            logger.error("Failed to extract text from Gemini response: %s", e)
            raise AIProviderError(
                message=f"Invalid response structure: {e}",
                provider=self.name,
            ) from e
