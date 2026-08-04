from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .refresh_orchestrator import refresh_platform_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-refresh",
        description="Refresh supported SuperModel datasets through the day before a slate.",
    )
    parser.add_argument("--date", required=True, help="Slate date in YYYY-MM-DD format")
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument(
        "--history-cache", type=Path, default=Path("runtime/data/mlb_completed_games.csv")
    )
    parser.add_argument(
        "--pitching-context", type=Path, default=Path("runtime/data/mlb_pitching_context.csv")
    )
    parser.add_argument(
        "--pitching-cache", type=Path, default=Path("runtime/cache/mlb_pitching_feeds")
    )
    parser.add_argument(
        "--state", type=Path, default=Path("runtime/state/platform_refresh.json")
    )
    parser.add_argument(
        "--quiet-progress",
        action="store_true",
        help="Suppress pitching progress messages so stdout remains machine-readable JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    def progress(index: int, total: int, game_pk: int, source: str) -> None:
        if not args.quiet_progress and (index == 1 or index == total or index % 25 == 0):
            print(
                f"Pitching refresh: {index}/{total} games (gamePk={game_pk}, {source})",
                file=sys.stderr,
                flush=True,
            )

    report = refresh_platform_data(
        slate_date=args.date,
        data_dir=args.data_dir,
        snapshot_dir=args.snapshot_dir,
        history_cache=args.history_cache,
        pitching_context_path=args.pitching_context,
        pitching_cache_dir=args.pitching_cache,
        state_path=args.state,
        progress_callback=progress,
    )
    print(json.dumps(report.to_record(), indent=2))


if __name__ == "__main__":
    main()
