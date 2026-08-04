from datetime import datetime, timedelta, timezone
import io

from supermodel.observability import structured_log
from supermodel.security import SlidingWindowRateLimiter, redact_secrets


def test_redaction_recurses_and_structured_logs_do_not_leak():
    payload = redact_secrets({"api_key": "abc", "nested": {"password": "secret", "ok": 1}})
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    stream = io.StringIO()
    structured_log("test", stream=stream, api_key="abc")
    assert "abc" not in stream.getvalue()
    assert "[REDACTED]" in stream.getvalue()


def test_sliding_window_rate_limit_resets():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    assert limiter.allow("client", now=now)
    assert limiter.allow("client", now=now)
    assert not limiter.allow("client", now=now)
    assert limiter.allow("client", now=now + timedelta(seconds=61))
