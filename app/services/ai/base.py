"""
Abstract base classes for AI provider integration.

This module provides a unified interface for different AI providers (Gemini, GLM, OpenAI, etc.)
enabling easy switching between providers and reuse across different AI-powered features.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Retry configuration for AI provider HTTP requests
AI_MAX_RETRIES = 3
AI_RETRY_MIN_WAIT = 2  # seconds
AI_RETRY_MAX_WAIT = 8  # seconds

# HTTP status codes that are transient and worth retrying
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable_error(exc: BaseException) -> bool:
    """Determine if an exception is transient and worth retrying."""
    # All httpx network-level errors (TimeoutException, ConnectError,
    # SendError, ReceiveError, PoolTimeout, etc.) are transient
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, AIProviderError) and exc.status_code in _RETRYABLE_STATUS_CODES:
        return True
    return False


class AIRole(str, Enum):
    """Message roles for AI conversations."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class AIMessage(BaseModel):
    """A message in an AI conversation."""
    role: AIRole
    content: str


class VisionInput(BaseModel):
    """Input for vision-capable AI models."""
    image_base64: str = Field(..., description="Base64-encoded image data")
    mime_type: str = Field(..., description="Image MIME type (image/jpeg, image/png, image/webp)")


class AIProviderConfig(BaseModel):
    """Configuration for an AI provider."""
    api_key: str = Field(..., description="API key for the provider")
    model: str = Field(..., description="Model name/ID to use")
    max_tokens: int = Field(default=4000, description="Maximum tokens in response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    timeout: int = Field(default=120, description="Request timeout in seconds")


class AIProvider(ABC):
    """
    Abstract base class for AI providers.

    All AI providers (Gemini, GLM, OpenAI, Anthropic, etc.) should implement this interface
    to ensure consistent behavior across the application.

    Example usage:
        provider = get_ai_provider(AIProviderType.GEMINI)
        response = await provider.complete(messages, vision_input)
    """

    def __init__(self, config: AIProviderConfig):
        self.config = config
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the reusable HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self.config.timeout,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=60,
                ),
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        """
        Execute an HTTP POST with automatic retries for transient errors.

        Uses tenacity with exponential backoff. Retries on:
        - Network errors (timeout, connect, send, receive)
        - HTTP 429 (rate limit), 500, 502, 503, 504

        Does NOT retry on auth errors (401, 403) or client errors (400).

        All exceptions are normalised to ``AIProviderError`` before
        propagating so callers only need to handle that single type.
        """
        @retry(
            stop=stop_after_attempt(AI_MAX_RETRIES),
            wait=wait_exponential(
                multiplier=1,
                min=AI_RETRY_MIN_WAIT,
                max=AI_RETRY_MAX_WAIT,
            ),
            retry=retry_if_exception(_is_retryable_error),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _do_post() -> httpx.Response:
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code in _RETRYABLE_STATUS_CODES:
                raise AIProviderError(
                    message=f"Retryable HTTP {response.status_code}: {response.text[:500]}",
                    provider=self.name,
                    status_code=response.status_code,
                    response_body=response.text[:1000],
                )

            if response.status_code >= 400:
                raise AIProviderError(
                    message=f"API request failed: {response.text[:500]}",
                    provider=self.name,
                    status_code=response.status_code,
                    response_body=response.text[:1000],
                )

            return response

        try:
            return await _do_post()
        except httpx.TimeoutException as exc:
            raise AIProviderError(
                message=f"Request timed out after {AI_MAX_RETRIES} attempts: {exc}",
                provider=self.name,
            ) from exc
        except httpx.RequestError as exc:
            raise AIProviderError(
                message=f"Request failed after {AI_MAX_RETRIES} attempts: {exc}",
                provider=self.name,
            ) from exc

    def _extract_balanced_json_object(self, text: str) -> str | None:
        """Return the first balanced JSON object embedded in text."""
        start = text.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escape = False

            for index in range(start, len(text)):
                char = text[index]

                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : index + 1]

            start = text.find("{", start + 1)

        return None

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Parse JSON from AI response text.

        Tries, in order:
        1. Direct ``json.loads``
        2. Extraction from markdown code fences (```json ... ```)
        3. The first balanced JSON object embedded in the text
        """
        try:
            return dict[str, Any](json.loads(text))
        except json.JSONDecodeError:
            pass

        # Markdown code block
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence_match:
            try:
                return dict[str, Any](json.loads(fence_match.group(1).strip()))
            except json.JSONDecodeError:
                pass

        # First balanced-brace JSON object
        json_object = self._extract_balanced_json_object(text)
        if json_object:
            try:
                return dict[str, Any](json.loads(json_object))
            except json.JSONDecodeError:
                pass

        raise AIProviderError(
            message="Failed to parse JSON from response",
            provider=self.name,
            response_body=text[:1000],
        )

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the provider."""
        pass

    @property
    @abstractmethod
    def supports_vision(self) -> bool:
        """Whether this provider supports vision/image inputs."""
        pass

    @property
    @abstractmethod
    def supports_json_mode(self) -> bool:
        """Whether this provider supports structured JSON output mode."""
        pass

    @abstractmethod
    async def complete(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
    ) -> str:
        """
        Generate a text completion from the AI model.

        Args:
            messages: List of conversation messages
            vision_input: Optional image input for vision models

        Returns:
            Generated text response

        Raises:
            AIProviderError: If the API call fails
        """
        pass

    @abstractmethod
    async def complete_json(
        self,
        messages: list[AIMessage],
        vision_input: VisionInput | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a structured JSON completion from the AI model.

        Args:
            messages: List of conversation messages
            vision_input: Optional image input for vision models
            json_schema: Optional JSON schema for structured output

        Returns:
            Parsed JSON response as a dictionary

        Raises:
            AIProviderError: If the API call fails or JSON parsing fails
        """
        pass


class AIProviderError(Exception):
    """Base exception for AI provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        base = f"[{self.provider}] {super().__str__()}"
        if self.status_code:
            base += f" (status: {self.status_code})"
        return base
