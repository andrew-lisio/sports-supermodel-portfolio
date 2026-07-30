from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from .worker import WorkerPolicy, run_worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-worker",
        description="Run the adaptive hosted refresh/publish loop.",
    )
    parser.add_argument("--once", action="store_true", help="Run one publisher cycle and exit")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument(
        "--timezone",
        default=os.environ.get("SPORTS_SUPERMODEL_TIMEZONE", "America/New_York"),
    )
    parser.add_argument("--base-seconds", type=int, default=1800)
    parser.add_argument("--near-game-seconds", type=int, default=600)
    parser.add_argument("--overnight-seconds", type=int, default=3600)
    parser.add_argument("--near-game-window-seconds", type=int, default=7200)
    parser.add_argument("--simulations", type=int, default=100_000)
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument("--market-store", type=Path, default=Path("runtime/markets"))
    parser.add_argument("--simulation-store", type=Path, default=Path("runtime/simulations"))
    parser.add_argument(
        "--bookmakers",
        default=os.environ.get(
            "SPORTS_SUPERMODEL_ODDS_BOOKMAKERS", "draftkings,fanduel,hardrockbet"
        ),
    )
    parser.add_argument("--require-odds", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    max_runs = 1 if args.once else args.max_runs
    policy = WorkerPolicy(
        timezone_name=args.timezone,
        base_interval_seconds=args.base_seconds,
        near_game_interval_seconds=args.near_game_seconds,
        overnight_interval_seconds=args.overnight_seconds,
        near_game_window_seconds=args.near_game_window_seconds,
    )
    run_worker(
        policy=policy,
        max_runs=max_runs,
        publish_kwargs={
            "data_dir": args.data_dir,
            "snapshot_dir": args.snapshot_dir,
            "market_store_root": args.market_store,
            "simulation_store_root": args.simulation_store,
            "simulations": args.simulations,
            "odds_bookmakers": tuple(
                item.strip() for item in args.bookmakers.split(",") if item.strip()
            ),
            "require_odds": args.require_odds,
        },
    )


if __name__ == "__main__":
    main()
