from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from typing import Callable
from zoneinfo import ZoneInfo

from .publisher import SlatePublishReport, publish_slate


@dataclass(frozen=True)
class WorkerPolicy:
    timezone_name: str = "America/New_York"
    base_interval_seconds: int = 1800
    near_game_interval_seconds: int = 600
    overnight_interval_seconds: int = 3600
    near_game_window_seconds: int = 7200

    def __post_init__(self) -> None:
        for value in (
            self.base_interval_seconds,
            self.near_game_interval_seconds,
            self.overnight_interval_seconds,
            self.near_game_window_seconds,
        ):
            if int(value) <= 0:
                raise ValueError("worker intervals must be positive")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def next_poll_seconds(
    *,
    now: datetime,
    next_game_start_utc: str | None,
    policy: WorkerPolicy,
) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(ZoneInfo(policy.timezone_name))
    start = _parse_utc(next_game_start_utc)
    if start is not None:
        seconds_to_start = (start - now.astimezone(timezone.utc)).total_seconds()
        if 0 < seconds_to_start <= policy.near_game_window_seconds:
            return policy.near_game_interval_seconds
    if 0 <= local_now.hour < 4:
        return policy.overnight_interval_seconds
    return policy.base_interval_seconds


def run_worker(
    *,
    policy: WorkerPolicy | None = None,
    max_runs: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now_factory: Callable[[], datetime] | None = None,
    publish: Callable[..., SlatePublishReport] = publish_slate,
    publish_kwargs: dict | None = None,
) -> list[SlatePublishReport]:
    if max_runs is not None and max_runs <= 0:
        raise ValueError("max_runs must be positive")
    active_policy = policy or WorkerPolicy()
    clock = now_factory or (lambda: datetime.now(timezone.utc))
    kwargs = dict(publish_kwargs or {})
    reports: list[SlatePublishReport] = []
    while max_runs is None or len(reports) < max_runs:
        now = clock()
        slate_date = now.astimezone(ZoneInfo(active_policy.timezone_name)).date().isoformat()
        try:
            report = publish(slate_date=slate_date, **kwargs)
        except Exception as exc:
            if max_runs is not None:
                raise
            print(
                json.dumps(
                    {
                        "status": "WORKER_ERROR",
                        "slate_date": slate_date,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            sleep(active_policy.base_interval_seconds)
            continue
        reports.append(report)
        print(json.dumps(report.to_record(), sort_keys=True), flush=True)
        if max_runs is not None and len(reports) >= max_runs:
            break
        sleep(
            next_poll_seconds(
                now=now,
                next_game_start_utc=report.next_game_start_utc,
                policy=active_policy,
            )
        )
    return reports
