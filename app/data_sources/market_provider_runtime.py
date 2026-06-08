from __future__ import annotations

import time

import httpx


FINMIND_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
FUGLE_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
PRICE_PROVIDER_KEYS = {"finmind", "fugle", "official_openapi"}


class MarketDataProviderUnavailable(RuntimeError):
    """Raised when a configured market data provider cannot be used."""


class ProviderCircuitBreaker:
    def __init__(
        self,
        provider: str,
        *,
        enabled: bool,
        failure_threshold: int,
        recovery_seconds: float,
        monotonic_clock=time.monotonic,
    ) -> None:
        self.provider = provider
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self.monotonic_clock = monotonic_clock
        self.failure_count = 0
        self.opened_at: float | None = None

    def configure(
        self,
        *,
        enabled: bool,
        failure_threshold: int,
        recovery_seconds: float,
    ) -> None:
        self.enabled = bool(enabled)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        if not self.enabled:
            self.failure_count = 0
            self.opened_at = None

    def before_call(self) -> None:
        if not self.enabled or self.opened_at is None:
            return
        elapsed = self.monotonic_clock() - self.opened_at
        if elapsed >= self.recovery_seconds:
            self.opened_at = None
            return
        raise MarketDataProviderUnavailable(
            f"{self.provider} circuit breaker is open; retry after {self.recovery_seconds - elapsed:.1f}s"
        )

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        if not self.enabled:
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = self.monotonic_clock()


def provider_circuit_setting(settings, provider: str, suffix: str, default):
    attr = f"{provider}_circuit_breaker_{suffix}"
    return getattr(settings, attr, default)


def configure_provider_circuit_breaker(
    settings,
    circuit_breakers: dict[str, ProviderCircuitBreaker],
    provider: str,
) -> ProviderCircuitBreaker:
    breaker = circuit_breakers[provider]
    breaker.configure(
        enabled=provider_circuit_setting(settings, provider, "enabled", True),
        failure_threshold=provider_circuit_setting(settings, provider, "failure_threshold", 5),
        recovery_seconds=provider_circuit_setting(settings, provider, "recovery_seconds", 60.0),
    )
    return breaker


def should_retry_status(
    status_code: int,
    attempt: int,
    *,
    retryable_statuses: set[int],
    max_retries: int,
) -> bool:
    return status_code in retryable_statuses and attempt < max(0, int(max_retries))


def retry_delay_seconds(
    response: httpx.Response | None,
    attempt: int,
    *,
    base_retry_delay_seconds: float,
    max_retry_delay_seconds: float,
) -> float:
    max_delay = max(0.0, float(max_retry_delay_seconds))
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max_delay, max(0.0, float(retry_after)))
            except ValueError:
                pass
    return min(max_delay, max(0.0, float(base_retry_delay_seconds)) * (2**attempt))


def market_price_provider_order(raw_order: object) -> list[str]:
    providers = str(raw_order or "finmind,fugle")
    normalized: list[str] = []
    for provider in providers.replace("\n", ",").split(","):
        provider = provider.strip().lower()
        if provider in PRICE_PROVIDER_KEYS and provider not in normalized:
            normalized.append(provider)
    return normalized or ["finmind"]
