# ADR 004: Adapter Pattern for External Services

**Status:** Accepted

**Date:** 2026-05-08

## Context

The 360Ghar backend integrates with several external HTTP services:

1. **AI Providers** — Google Gemini (`app/services/ai/providers/gemini.py`) and ZhipuAI GLM (`app/services/ai/providers/glm.py`) for chat completions, vision analysis, and structured JSON generation.

2. **Supabase** — Auth verification and REST API for notifications/push (`app/services/notifications.py`).

3. **Firebase Cloud Messaging (FCM)** — Push notifications (`app/services/notifications.py` → `app/services/push_notification.py`).

4. **Email** — Transactional email delivery (`app/services/email.py`).

5. **SMS** — SMS delivery (`app/services/sms.py`).

6. **Storage** — File upload/storage (Supabase Storage via `app/services/storage/`).

7. **Data Hub Scrapers** — 15+ scraper modules in `app/services/data_hub/` that make HTTP requests to external data sources (bank auctions, court auctions, RERA, circle rates, etc.).

### Current AI Provider Pattern

The AI provider layer (`app/services/ai/`) already demonstrates a well-structured adapter pattern:

- `AIProvider` — Abstract base class with `complete()` and `complete_json()` abstract methods.
- `GeminiProvider(AIProvider)` — Concrete implementation for Google Gemini.
- `GLMProvider(AIProvider)` — Concrete implementation for ZhipuAI GLM.
- `get_ai_provider()` — Factory function that creates the right provider based on `AIProviderType` enum.
- `_make_request()` — Base class method that centralizes HTTP request execution with tenacity retries, exponential backoff, and error normalization to `AIProviderError`.
- Both providers reuse the base class's `httpx.AsyncClient` management (connection pooling, keepalive, timeout).

This is a good pattern but has gaps:

1. **Retry and circuit-breaking are only in AI providers.** Other external services (Supabase, FCM, email, SMS, scrapers) implement their own error handling inconsistently. Some have no retries; others have hand-rolled try/except with logging.

2. **No circuit breaking.** If Gemini's API is down, every request still tries to hit it, waiting for the full timeout and retry cycle. There is no mechanism to short-circuit requests when a provider is known to be unhealthy.

3. **Duplicated HTTP client setup.** While the AI providers share a base `httpx.AsyncClient`, other services create their own clients with different configurations (timeouts, connection limits, retry policies).

4. **No provider health tracking.** There is no centralized way to know which external services are healthy, how many requests they're handling, or what their error rates are.

5. **Scrapers have no standardized interface.** The 15 data hub scrapers each implement their own HTTP fetching, parsing, and error handling with no shared contract.

### Current Service Integration Points

```
┌───────────────────────────────────────────────────┐
│                  Service Layer                      │
│                                                    │
│  BlogService ───► httpx ──► Gemini API             │
│  VastuAnalyzer ──► httpx ──► Gemini API            │
│  TourAI ─────────► httpx ──► Gemini API             │
│  AI Agent ───────► get_ai_provider() ──► Gemini/GLM│
│                                                    │
│  BookingService ──► send_email() ──► SMTP/API       │
│  NotificationDisp► send_sms() ────► SMS Gateway     │
│  PushNotification► send_to_user() ──► FCM           │
│  NotificationDisp► send_to_user() ──► Supabase Push │
│                                                    │
│  DataHubScrapers ──► httpx ──► Various sites       │
│  StorageService ───► Supabase Storage API           │
└───────────────────────────────────────────────────┘
```

## Decision

Formalize the **Adapter Pattern** for all external service integrations. Each external service is wrapped behind an adapter interface that centralizes retry, circuit-breaking, timeout, and health tracking. Business code depends on adapter interfaces, not on raw HTTP clients.

### Architecture

```
┌───────────────────────────────────────────────────┐
│                  Service Layer                      │
│  (depends on adapter protocols only)                │
│                                                    │
│  BlogService ───► AIAdapter.complete()             │
│  VastuAnalyzer ──► AIAdapter.complete()             │
│  NotificationDisp► EmailAdapter.send()              │
│  NotificationDisp► SMSAdapter.send()               │
│  NotificationDisp► PushAdapter.send()               │
│  DataHubScrapers ► ScraperAdapter.fetch()           │
└───────────┬───────────────────────────────────────┘
            │ depends on
            ▼
┌───────────────────────────────────────────────────┐
│              Adapter Protocol Interfaces            │
│                                                    │
│  AIAdapter (Protocol)                              │
│  EmailAdapter (Protocol)                           │
│  SMSAdapter (Protocol)                             │
│  PushAdapter (Protocol)                            │
│  ScraperAdapter (Protocol)                         │
│  StorageAdapter (Protocol)                         │
└───────────┬───────────────────────────────────────┘
            │ implemented by
            ▼
┌───────────────────────────────────────────────────┐
│            Concrete Adapters                        │
│                                                    │
│  GeminiAIAdapter ◄── AIAdapter                     │
│  GLMAIAdapter ◄───── AIAdapter                     │
│  SMTPEmailAdapter ◄─ EmailAdapter                  │
│  TwilioSMSAdapter ◄── SMSAdapter                   │
│  FCMPushAdapter ◄──── PushAdapter                  │
│  SupabaseStorageAdapter ◄── StorageAdapter         │
│  BankAuctionScraperAdapter ◄── ScraperAdapter       │
│  ...                                                │
│                                                    │
│  Each adapter includes:                            │
│  ✓ Retry (tenacity)                                │
│  ✓ Circuit breaker                                 │
│  ✓ Timeout                                         │
│  ✓ Health tracking                                 │
│  ✓ Error normalization                             │
└───────────────────────────────────────────────────┘
```

### Adapter Protocol Interface

```python
# app/shared/adapters/protocols.py

from typing import Protocol, Any, Optional

class AIAdapter(Protocol):
    """Interface for AI completion providers."""

    @property
    def name(self) -> str: ...

    @property
    def is_healthy(self) -> bool: ...

    async def complete(
        self,
        messages: list[Any],
        vision_input: Any | None = None,
    ) -> str: ...

    async def complete_json(
        self,
        messages: list[Any],
        vision_input: Any | None = None,
        json_schema: dict | None = None,
    ) -> dict[str, Any]: ...


class EmailAdapter(Protocol):
    """Interface for email delivery providers."""

    @property
    def is_healthy(self) -> bool: ...

    async def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> bool: ...


class SMSAdapter(Protocol):
    """Interface for SMS delivery providers."""

    @property
    def is_healthy(self) -> bool: ...

    async def send(
        self,
        phone_number: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool: ...


class PushAdapter(Protocol):
    """Interface for push notification providers."""

    @property
    def is_healthy(self) -> bool: ...

    async def send_to_token(
        self,
        token: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...

    async def send_to_user(
        self,
        user_id: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class ScraperAdapter(Protocol):
    """Interface for data hub scraper integrations."""

    @property
    def name(self) -> str: ...

    @property
    def is_healthy(self) -> bool: ...

    async def fetch(self, **params) -> list[dict[str, Any]]:
        """Fetch data from the external source."""
        ...


class StorageAdapter(Protocol):
    """Interface for file storage providers."""

    @property
    def is_healthy(self) -> bool: ...

    async def upload(
        self, path: str, data: bytes, content_type: str
    ) -> str: ...

    async def download(self, path: str) -> bytes: ...

    async def delete(self, path: str) -> bool: ...

    async def get_signed_url(
        self, path: str, expires_in: int = 3600
    ) -> str: ...
```

### Circuit Breaker

A lightweight circuit breaker prevents cascading failures when an external service is unhealthy:

```python
# app/shared/adapters/circuit_breaker.py

import time
from enum import Enum
from typing import Optional

class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, requests rejected
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    - After `failure_threshold` consecutive failures, the circuit opens.
    - In OPEN state, requests immediately fail without calling the service.
    - After `recovery_timeout` seconds, the circuit enters HALF_OPEN.
    - A successful request in HALF_OPEN closes the circuit.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self.state == CircuitState.OPEN:
            if (
                self.last_failure_time
                and time.monotonic() - self.last_failure_time
                > self.recovery_timeout
            ):
                self.state = CircuitState.HALF_OPEN
                return False
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
```

### Concrete Adapter Example (Gemini)

Refactoring the existing `GeminiProvider` to add circuit breaking:

```python
# app/shared/adapters/gemini_adapter.py

from app.shared.adapters.circuit_breaker import CircuitBreaker
from app.services.ai.base import AIProvider, AIProviderConfig, AIProviderError
from app.services.ai.providers.gemini import GeminiProvider

class GeminiAIAdapter:
    """Gemini AI adapter with circuit breaking and health tracking.

    Wraps the existing GeminiProvider and adds:
    - Circuit breaker to short-circuit requests when Gemini is down
    - Health status tracking
    - Consistent error handling
    """

    def __init__(self, provider: GeminiProvider):
        self._provider = provider
        self._circuit = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def is_healthy(self) -> bool:
        return not self._circuit.is_open

    async def complete(self, messages, vision_input=None) -> str:
        if self._circuit.is_open:
            raise AIProviderError(
                message="Circuit breaker is open; Gemini unavailable",
                provider=self.name,
            )
        try:
            result = await self._provider.complete(messages, vision_input)
            self._circuit.record_success()
            return result
        except AIProviderError:
            self._circuit.record_failure()
            raise

    async def complete_json(self, messages, vision_input=None, json_schema=None) -> dict:
        if self._circuit.is_open:
            raise AIProviderError(
                message="Circuit breaker is open; Gemini unavailable",
                provider=self.name,
            )
        try:
            result = await self._provider.complete_json(
                messages, vision_input, json_schema
            )
            self._circuit.record_success()
            return result
        except AIProviderError:
            self._circuit.record_failure()
            raise
```

### Adapter Factory

```python
# app/shared/adapters/factory.py

from app.core.config import settings
from app.shared.adapters.protocols import AIAdapter, EmailAdapter, SMSAdapter, PushAdapter

class AdapterFactory:
    """Factory for creating configured adapter instances."""

    @staticmethod
    def get_ai_adapter(provider_type: str = "gemini") -> AIAdapter:
        from app.services.ai import get_ai_provider, AIProviderType
        from app.shared.adapters.gemini_adapter import GeminiAIAdapter
        from app.shared.adapters.glm_adapter import GLMAIAdapter

        provider = get_ai_provider(AIProviderType(provider_type))
        if provider_type == "gemini":
            return GeminiAIAdapter(provider)
        elif provider_type == "glm":
            return GLMAIAdapter(provider)
        raise ValueError(f"Unknown AI provider: {provider_type}")

    @staticmethod
    def get_email_adapter() -> EmailAdapter:
        from app.shared.adapters.smtp_adapter import SMTPEmailAdapter
        return SMTPEmailAdapter(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
        )

    @staticmethod
    def get_sms_adapter() -> SMSAdapter:
        from app.shared.adapters.twilio_sms_adapter import TwilioSMSAdapter
        return TwilioSMSAdapter(
            account_sid=settings.SMS_ACCOUNT_SID,
            auth_token=settings.SMS_AUTH_TOKEN,
            from_number=settings.SMS_FROM_NUMBER,
        )

    @staticmethod
    def get_push_adapter() -> PushAdapter:
        from app.shared.adapters.fcm_push_adapter import FCMPushAdapter
        return FCMPushAdapter(
            project_id=settings.FIREBASE_PROJECT_ID,
            service_account_path=settings.FIREBASE_SERVICE_ACCOUNT_PATH,
        )
```

### Relationship to Existing AI Provider Architecture

The existing `app/services/ai/` architecture is well-designed and serves as the model for this ADR. The adapter layer **wraps** the existing providers rather than replacing them:

```
Before:
  BlogService → get_ai_provider() → GeminiProvider → httpx → Gemini API

After:
  BlogService → AdapterFactory.get_ai_adapter() → GeminiAIAdapter → GeminiProvider → httpx → Gemini API
                                                              │
                                                              └── CircuitBreaker
                                                              └── Health tracking
```

The existing `AIProvider` abstract class, `GeminiProvider`, and `GLMProvider` remain unchanged. The adapter layer adds circuit breaking, health tracking, and the protocol interface on top.

### Scraper Adapter Pattern

Data hub scrapers currently have no shared interface. The adapter pattern standardizes them:

```python
# app/shared/adapters/base_scraper.py

from abc import ABC, abstractmethod
from typing import Any
from app.shared.adapters.circuit_breaker import CircuitBreaker

class BaseScraperAdapter(ABC):
    """Base class for data hub scraper adapters."""

    def __init__(self, circuit: CircuitBreaker | None = None):
        self._circuit = circuit or CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60.0,  # Longer recovery for scrapers
        )

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def is_healthy(self) -> bool:
        return not self._circuit.is_open

    @abstractmethod
    async def _do_fetch(self, **params) -> list[dict[str, Any]]:
        """Actual fetch implementation. Subclasses override this."""
        ...

    async def fetch(self, **params) -> list[dict[str, Any]]:
        if self._circuit.is_open:
            raise RuntimeError(f"Circuit breaker open for {self.name}")
        try:
            result = await self._do_fetch(**params)
            self._circuit.record_success()
            return result
        except Exception:
            self._circuit.record_failure()
            raise
```

## Consequences

### Positive

- **Swappable providers.** Switching from Gemini to a new AI provider requires only a new adapter class and a factory config change. Business code is untouched.

- **Centralized resilience.** Retry, circuit-breaking, and timeout logic lives in the adapter layer, not scattered across services. Adding a new resilience policy (e.g., rate limiting) requires one change.

- **Health visibility.** The `is_healthy` property on each adapter enables health-check endpoints and monitoring dashboards to report external service status.

- **Consistent error handling.** All adapter errors are normalized to adapter-specific exceptions (e.g., `AIProviderError`, `EmailDeliveryError`, `SMSSendError`). Business code handles a small set of known errors.

- **Better testability.** Services depend on adapter protocols, which can be mocked with `AsyncMock`. No need to mock `httpx` or network calls in service-level tests.

- **Scraper standardization.** Data hub scrapers gain a shared interface, making it easier to add new data sources and maintain existing ones.

### Negative

- **Additional abstraction layer.** The adapter pattern adds one more layer between business code and external services. For simple integrations (e.g., email), the overhead may feel unjustified.

- **Circuit breaker tuning.** Circuit breaker thresholds and recovery timeouts must be tuned per service. A one-size-fits-all configuration (5 failures / 30 seconds) may not work for all providers. Scrapers, for example, may need longer recovery times.

- **Adapter state management.** Circuit breakers are stateful. In a multi-process deployment (multiple Gunicorn workers, Kubernetes pods), circuit state is per-process. A failure on one worker does not open the circuit on others. This can be addressed with a shared Redis-backed circuit breaker in the future.

- **Migration effort.** Existing service code that calls external services directly must be refactored to use adapters. The AI provider layer is already well-structured, but email, SMS, push, and scraper integrations need refactoring.

- **No built-in fallback.** The initial design does not include automatic fallback (e.g., "if Gemini is down, try GLM"). This can be added as a `FallbackAIAdapter` that tries multiple providers in sequence, but it adds complexity.

## Migration Strategy

### Phase 1: Define Adapter Protocols and Infrastructure (1 week)

1. Create `app/shared/adapters/` directory.
2. Define adapter protocol interfaces (`AIAdapter`, `EmailAdapter`, `SMSAdapter`, `PushAdapter`, `StorageAdapter`, `ScraperAdapter`).
3. Implement `CircuitBreaker` class.
4. Implement `AdapterFactory`.
5. Wire adapter creation into `app/infrastructure/lifespan.py` startup.

### Phase 2: Wrap AI Providers (1 week)

The AI providers are the best starting point because they already follow an adapter-like pattern:

1. Create `GeminiAIAdapter` and `GLMAIAdapter` wrapping the existing `GeminiProvider` and `GLMProvider`.
2. Add circuit breaking and health tracking.
3. Update `get_ai_provider()` or replace with `AdapterFactory.get_ai_adapter()`.
4. Update consumers: `BlogService`, `VastuAnalyzer`, `TourAI`, `AI Agent`.

### Phase 3: Wrap Notification Adapters (1 week)

1. Create `SMTPEmailAdapter` wrapping `app/services/email.py`.
2. Create `FCMPushAdapter` wrapping `app/services/notifications.py` (FCM path).
3. Create `TwilioSMSAdapter` wrapping `app/services/sms.py`.
4. Update `notification_dispatcher.py` to use adapter interfaces instead of direct service calls.

### Phase 4: Wrap Storage and Scrapers (2 weeks)

1. Create `SupabaseStorageAdapter` wrapping `app/services/storage/`.
2. Create `BaseScraperAdapter` and implement adapters for each data hub scraper.
3. Update `data_hub_scheduler.py` to use scraper adapters.

### Phase 5: Add Fallback and Monitoring (optional, future)

1. Implement `FallbackAIAdapter` that tries Gemini, then GLM, then returns an error.
2. Add adapter health to the `/health` endpoint.
3. Add Prometheus metrics for adapter call counts, latency, and error rates.
4. Implement Redis-backed circuit breaker for multi-process deployments.

### Rollback Plan

Each adapter migration is independently revertible:
- Remove the adapter wrapper.
- Restore direct service calls in the consuming code.
- The adapter protocol and concrete adapter can remain as dead code without affecting runtime.
- Circuit breakers that are never queried have no effect.
