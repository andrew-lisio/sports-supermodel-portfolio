from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from .security import redact_secrets


@dataclass(frozen=True)
class LogEvent:
    timestamp_utc: str
    level: str
    event: str
    service: str
    fields: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def structured_log(
    event: str,
    *,
    level: str = "INFO",
    service: str = "sports-supermodel",
    stream: TextIO | None = None,
    **fields: Any,
) -> dict[str, Any]:
    record = LogEvent(
        timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        level=str(level).upper(),
        event=str(event),
        service=str(service),
        fields=redact_secrets(fields),
    ).to_record()
    target = stream or sys.stdout
    target.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    target.flush()
    return record


def write_alert(
    message: str,
    *,
    severity: str,
    root: str | Path = "runtime/alerts",
    details: dict[str, Any] | None = None,
) -> Path:
    timestamp = datetime.now(timezone.utc)
    payload = {
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "severity": severity.upper(),
        "message": message,
        "details": redact_secrets(details or {}),
    }
    path = Path(root) / timestamp.strftime("%Y-%m-%d") / f"{timestamp.strftime('%H%M%S%f')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
