from __future__ import annotations

import argparse
import json
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Sequence
from zoneinfo import ZoneInfo

from .publisher import publish_slate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-publish",
        description=(
            "Refresh supported inputs and centrally publish changed pregame "
            "100,000-simulation snapshots."
        ),
    )
    parser.add_argument(
        "--date",
        help="Slate date in YYYY-MM-DD format; defaults to today in the configured timezone",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/reports"))
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
        "--refresh-state", type=Path, default=Path("runtime/state/platform_refresh.json")
    )
    parser.add_argument(
        "--publisher-state", type=Path, default=Path("runtime/state/slate_publisher.json")
    )
    parser.add_argument(
        "--publisher-reports", type=Path, default=Path("runtime/reports/slate_publisher")
    )
    parser.add_argument(
        "--publisher-lock", type=Path, default=Path("runtime/state/slate_publisher.lock")
    )
    parser.add_argument("--market-store", type=Path, default=Path("runtime/markets"))
    parser.add_argument(
        "--simulation-store", type=Path, default=Path("runtime/simulations")
    )
    parser.add_argument("--simulations", type=int, default=100_000)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument(
        "--bookmakers",
        default=os.environ.get(
            "SPORTS_SUPERMODEL_ODDS_BOOKMAKERS", "draftkings,fanduel,hardrockbet"
        ),
        help="Comma-separated The Odds API bookmaker keys",
    )
    parser.add_argument(
        "--odds-markets",
        default="h2h,spreads,totals",
        help="Comma-separated featured provider market keys",
    )
    parser.add_argument(
        "--require-odds",
        action="store_true",
        help="Fail the publisher if a configured odds provider cannot refresh",
    )
    parser.add_argument(
        "--timezone",
        default=os.environ.get("SPORTS_SUPERMODEL_TIMEZONE", "America/New_York"),
    )
    parser.add_argument("--force", action="store_true", help="Republish every eligible game")
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip completed-history and pitching refresh for this invocation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.simulations <= 0:
        raise SystemExit("--simulations must be positive")

    def progress(index: int, total: int, game_pk: int, source: str) -> None:
        if index == 1 or index == total or index % 25 == 0:
            print(
                f"Pitching refresh: {index}/{total} games (gamePk={game_pk}, {source})",
                file=sys.stderr,
                flush=True,
            )

    slate_date = args.date or datetime.now(ZoneInfo(args.timezone)).date().isoformat()
    report = publish_slate(
        slate_date=slate_date,
        data_dir=args.data_dir,
        snapshot_dir=args.snapshot_dir,
        output_dir=args.output_dir,
        history_cache_path=args.history_cache,
        pitching_context_path=args.pitching_context,
        pitching_cache_dir=args.pitching_cache,
        refresh_state_path=args.refresh_state,
        publisher_state_path=args.publisher_state,
        publisher_report_root=args.publisher_reports,
        publisher_lock_path=args.publisher_lock,
        market_store_root=args.market_store,
        simulation_store_root=args.simulation_store,
        simulations=args.simulations,
        top_n=args.top_n,
        force=args.force,
        refresh=not args.skip_refresh,
        progress_callback=progress,
        odds_bookmakers=tuple(item.strip() for item in args.bookmakers.split(",") if item.strip()),
        odds_markets=tuple(item.strip() for item in args.odds_markets.split(",") if item.strip()),
        require_odds=args.require_odds,
    )
    print(json.dumps(report.to_record(), indent=2))


if __name__ == "__main__":
    main()
