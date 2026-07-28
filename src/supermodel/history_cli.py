from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from .game_registry import ImmutableSnapshotStore, parse_mlb_schedule
from .history_refresh import refresh_completed_history
from .live_mlb import MLBStatsHTTPClient
from .mlb_v2 import attach_official_home_away, load_team_logs, reconstruct_games


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-history",
        description=(
            "Refresh the local completed-game cache through the day before a slate. "
            "The same fail-closed refresh runs automatically during every evaluation."
        ),
    )
    parser.add_argument("--date", required=True, help="Upcoming slate date in YYYY-MM-DD format")
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument(
        "--history-cache",
        type=Path,
        default=Path("runtime/data/mlb_completed_games.csv"),
    )
    return parser


def run(args: argparse.Namespace) -> dict:
    client = MLBStatsHTTPClient()
    captured_at = datetime.now(timezone.utc)
    store = ImmutableSnapshotStore(args.snapshot_dir)
    logs = load_team_logs(args.data_dir)
    games = reconstruct_games(logs)
    history_start = pd.to_datetime(games["date"]).min().date().isoformat()
    base_history_end = pd.to_datetime(games["date"]).max().date().isoformat()
    identity_payload = client.schedule_range(history_start, base_history_end)
    store.write_schedule(
        raw_payload=identity_payload,
        captured_at=captured_at,
        source="mlb_stats_api:v1/schedule:historical_identity_backfill",
    )
    games = attach_official_home_away(games, parse_mlb_schedule(identity_payload))
    _, report = refresh_completed_history(
        games,
        slate_date=args.date,
        client=client,
        snapshot_store=store,
        captured_at=captured_at,
        cache_path=args.history_cache,
    )
    return report.to_record()


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
