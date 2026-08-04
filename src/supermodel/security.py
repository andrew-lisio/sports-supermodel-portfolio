from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import os
import re
from threading import Lock
from typing import Any, Mapping

from .storage import ObjectBackend, StorageBackend, StorageSettings


_SECRET_PATTERN = re.compile(
    r"(key|token|secret|password|credential|authorization|database_url|dsn)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SecuritySettings:
    environment: str = "development"
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    trust_proxy_headers: bool = False
    require_https: bool = False
    admin_token_configured: bool = False

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        environment = os.environ.get("SPORTS_SUPERMODEL_ENV", "development").strip().lower()
        return cls(
            environment=environment,
            rate_limit_requests=int(os.environ.get("SPORTS_SUPERMODEL_RATE_LIMIT", "120")),
            rate_limit_window_seconds=int(
                os.environ.get("SPORTS_SUPERMODEL_RATE_LIMIT_WINDOW", "60")
            ),
            trust_proxy_headers=os.environ.get(
                "SPORTS_SUPERMODEL_TRUST_PROXY_HEADERS", "0"
            )
            == "1",
            require_https=os.environ.get("SPORTS_SUPERMODEL_REQUIRE_HTTPS", "0") == "1",
            admin_token_configured=bool(os.environ.get("SPORTS_SUPERMODEL_ADMIN_TOKEN")),
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("rate-limit values must be positive")
        self.limit = int(limit)
        self.window = timedelta(seconds=int(window_seconds))
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: datetime | None = None) -> bool:
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        cutoff = timestamp - self.window
        with self._lock:
            bucket = self._events[str(key)]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(timestamp)
            return True


def redact_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_PATTERN.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


def launch_readiness(
    *,
    storage: StorageSettings | None = None,
    security: SecuritySettings | None = None,
    require_odds: bool = True,
) -> dict[str, Any]:
    storage_settings = storage or StorageSettings.from_env()
    security_settings = security or SecuritySettings.from_env()
    failures: list[str] = []
    warnings: list[str] = []
    if security_settings.environment == "production":
        if storage_settings.backend is not StorageBackend.POSTGRES:
            failures.append("PRODUCTION_REQUIRES_POSTGRES")
        if storage_settings.object_backend is not ObjectBackend.S3:
            failures.append("PRODUCTION_REQUIRES_OBJECT_STORAGE")
        if not security_settings.admin_token_configured:
            failures.append("ADMIN_TOKEN_NOT_CONFIGURED")
        if not security_settings.require_https:
            warnings.append("HTTPS_ENFORCEMENT_NOT_DECLARED")
    if require_odds and not os.environ.get("SPORTS_SUPERMODEL_ODDS_API_KEY"):
        failures.append("ODDS_API_KEY_NOT_CONFIGURED")
    if not os.environ.get("SPORTS_SUPERMODEL_ALERT_WEBHOOK"):
        warnings.append("ALERT_WEBHOOK_NOT_CONFIGURED")
    return {
        "status": "PASS" if not failures else "FAIL",
        "environment": security_settings.environment,
        "failures": failures,
        "warnings": warnings,
        "storage": storage_settings.to_record(),
        "security": security_settings.to_record(),
    }
