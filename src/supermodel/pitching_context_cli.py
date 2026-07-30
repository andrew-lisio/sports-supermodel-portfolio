from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .live_mlb import MLBStatsHTTPClient
from .pitching_context import audit_pitching_context, fetch_pitching_context, write_pitching_context

DEFAULT_OUTPUT = Path("runtime/data/mlb_pitching_context.csv")
DEFAULT_CACHE_DIR = Path("runtime/cache/mlb_pitching_feeds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-pitching",
        description="Backfill and audit point-in-time starter/bullpen context.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    backfill = subparsers.add_parser("backfill")
    backfill.add_argument("--start-date", required=True)
    backfill.add_argument("--end-date", required=True)
    backfill.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    backfill.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    backfill.add_argument("--no-cache", action="store_true")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--path", type=Path, default=DEFAULT_OUTPUT)
    return parser


def run(args: argparse.Namespace) -> dict:
    if args.command == "audit":
        return audit_pitching_context(args.path)
    def progress(index: int, total: int, game_pk: int, source: str) -> None:
        if index == 1 or index == total or index % 25 == 0:
            print(
                f"Pitching backfill: {index}/{total} games "
                f"(gamePk={game_pk}, {source})",
                file=sys.stderr,
                flush=True,
            )

    frame = fetch_pitching_context(
        MLBStatsHTTPClient(),
        start_date=args.start_date,
        end_date=args.end_date,
        cache_dir=None if args.no_cache else args.cache_dir,
        progress_callback=progress,
    )
    write_pitching_context(args.output, frame)
    return audit_pitching_context(args.output)


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
