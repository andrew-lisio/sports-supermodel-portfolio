from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from .odds_provider import TheOddsAPIClient, refresh_the_odds_api
from .providers import PregameContext
from .workflow import capture_official_slate


def _is_pregame(context: PregameContext, captured_at: datetime) -> bool:
    status = " ".join(
        str(value or "") for value in (context.status_abstract, context.status_detailed)
    ).casefold()
    if any(
        token in status
        for token in (
            "final",
            "completed",
            "cancelled",
            "canceled",
            "postponed",
            "suspended",
            "in progress",
            "live",
        )
    ):
        return False
    if not context.game_datetime:
        return False
    try:
        start = datetime.fromisoformat(context.game_datetime.replace("Z", "+00:00"))
    except ValueError:
        return False
    if start.tzinfo is None or start.utcoffset() is None:
        start = start.replace(tzinfo=timezone.utc)
    return captured_at < start.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-odds",
        description="Refresh licensed MLB moneyline, spread, and total quotes.",
    )
    parser.add_argument("--date", help="YYYY-MM-DD; defaults to today in the configured timezone")
    parser.add_argument(
        "--timezone",
        default=os.environ.get("SPORTS_SUPERMODEL_TIMEZONE", "America/New_York"),
    )
    parser.add_argument(
        "--bookmakers",
        default=os.environ.get(
            "SPORTS_SUPERMODEL_ODDS_BOOKMAKERS", "draftkings,fanduel,hardrockbet"
        ),
    )
    parser.add_argument("--markets", default="h2h,spreads,totals")
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument("--market-store", type=Path, default=Path("runtime/markets"))
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("SPORTS_SUPERMODEL_ODDS_API_KEY")
    if not api_key:
        raise SystemExit("SPORTS_SUPERMODEL_ODDS_API_KEY is not configured")
    slate_date = args.date or datetime.now(ZoneInfo(args.timezone)).date().isoformat()
    captured_at = datetime.now(timezone.utc)
    captured = capture_official_slate(
        game_date=slate_date,
        snapshot_dir=args.snapshot_dir,
        captured_at=captured_at,
    )
    report = refresh_the_odds_api(
        client=TheOddsAPIClient(api_key),
        slate_date=slate_date,
        contexts=tuple(
            context for context in captured.contexts if _is_pregame(context, captured_at)
        ),
        market_store_root=args.market_store,
        raw_snapshot_root=args.snapshot_dir / "odds" / "the_odds_api",
        bookmakers=tuple(item.strip() for item in args.bookmakers.split(",") if item.strip()),
        markets=tuple(item.strip() for item in args.markets.split(",") if item.strip()),
        captured_at=captured_at,
    )
    print(json.dumps(report.to_record(), indent=2))


if __name__ == "__main__":
    main()
