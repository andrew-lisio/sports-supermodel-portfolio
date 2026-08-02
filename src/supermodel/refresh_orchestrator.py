from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .game_registry import ImmutableSnapshotStore, parse_mlb_schedule
from .history_refresh import refresh_completed_history
from .live_mlb import MLBStatsHTTPClient
from .mlb_v2 import attach_official_home_away, load_team_logs, reconstruct_games
from .pitching_context import audit_pitching_context, fetch_pitching_context, write_pitching_context
from .storage import StorageSettings, create_state_store


@dataclass(frozen=True)
class RefreshStep:
    name: str
    status: str
    details: dict[str, Any]


@dataclass(frozen=True)
class PlatformRefreshReport:
    status: str
    slate_date: str
    generated_at_utc: str
    steps: tuple[RefreshStep, ...]
    state_path: str
    storage_backend: str
    shared_state_ref: str | None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [asdict(step) for step in self.steps]
        return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def refresh_platform_data(
    *,
    slate_date: str,
    data_dir: str | Path = "data/2026",
    snapshot_dir: str | Path = "runtime/snapshots",
    history_cache: str | Path = "runtime/data/mlb_completed_games.csv",
    pitching_context_path: str | Path = "runtime/data/mlb_pitching_context.csv",
    pitching_cache_dir: str | Path = "runtime/cache/mlb_pitching_feeds",
    state_path: str | Path = "runtime/state/platform_refresh.json",
    client: MLBStatsHTTPClient | None = None,
    progress_callback: Callable[[int, int, int, str], None] | None = None,
) -> PlatformRefreshReport:
    """Refresh all currently supported local datasets through the day before a slate.

    Pitching context is rebuilt from the season start for point-in-time correctness, but
    cached game feeds mean only newly completed games require network downloads.
    """

    target_date = pd.Timestamp(slate_date).date()
    through_date = target_date - timedelta(days=1)
    captured_at = datetime.now(timezone.utc)
    api_client = client or MLBStatsHTTPClient()
    store = ImmutableSnapshotStore(snapshot_dir)
    steps: list[RefreshStep] = []

    logs = load_team_logs(Path(data_dir))
    games = reconstruct_games(logs)
    season_start = pd.to_datetime(games["date"]).min().date().isoformat()
    base_history_end = pd.to_datetime(games["date"]).max().date().isoformat()
    identity_payload = api_client.schedule_range(season_start, base_history_end)
    store.write_schedule(
        raw_payload=identity_payload,
        captured_at=captured_at,
        source="mlb_stats_api:v1/schedule:historical_identity_backfill",
    )
    games = attach_official_home_away(games, parse_mlb_schedule(identity_payload))
    _, history_report = refresh_completed_history(
        games,
        slate_date=target_date.isoformat(),
        client=api_client,
        snapshot_store=store,
        captured_at=captured_at,
        cache_path=history_cache,
    )
    steps.append(RefreshStep("completed_history", "PASS", history_report.to_record()))

    pitching_frame = fetch_pitching_context(
        api_client,
        start_date=season_start,
        end_date=through_date.isoformat(),
        cache_dir=pitching_cache_dir,
        progress_callback=progress_callback,
    )
    write_pitching_context(pitching_context_path, pitching_frame)
    pitching_audit = audit_pitching_context(pitching_context_path)
    expected_max = through_date.isoformat()
    pitching_status = (
        "PASS"
        if pitching_audit.get("status") == "PASS"
        and pitching_audit.get("date_max") == expected_max
        else "FAIL"
    )
    pitching_details = dict(pitching_audit)
    pitching_details["required_through_date"] = expected_max
    pitching_details["network_behavior"] = "cached historical feeds; fetch only uncached games"
    steps.append(RefreshStep("pitching_context", pitching_status, pitching_details))

    for pending in ("schedule_and_starters", "lineups_and_rosters", "weather", "sportsbook_odds"):
        steps.append(
            RefreshStep(
                pending,
                "PENDING_PROVIDER",
                {"message": "Provider interface reserved; no configured production source yet."},
            )
        )

    status = "PASS" if all(step.status in {"PASS", "PENDING_PROVIDER"} for step in steps) else "FAIL"
    target_state_path = Path(state_path)
    storage_settings = StorageSettings.from_env()
    report = PlatformRefreshReport(
        status=status,
        slate_date=target_date.isoformat(),
        generated_at_utc=captured_at.isoformat().replace("+00:00", "Z"),
        steps=tuple(steps),
        state_path=str(target_state_path),
        storage_backend=str(storage_settings.backend),
        shared_state_ref=None,
    )
    _write_json_atomic(target_state_path, report.to_record())
    state_store = create_state_store(
        target_state_path.parent / "shared",
        settings=storage_settings,
    )
    shared_ref = state_store.write(
        f"platform_refresh/{target_date.isoformat()}", report.to_record()
    )
    state_store.write("platform_refresh/latest", report.to_record())
    report = PlatformRefreshReport(
        status=report.status,
        slate_date=report.slate_date,
        generated_at_utc=report.generated_at_utc,
        steps=report.steps,
        state_path=report.state_path,
        storage_backend=report.storage_backend,
        shared_state_ref=shared_ref,
    )
    _write_json_atomic(target_state_path, report.to_record())
    state_store.write(
        f"platform_refresh/{target_date.isoformat()}", report.to_record()
    )
    state_store.write("platform_refresh/latest", report.to_record())
    return report
