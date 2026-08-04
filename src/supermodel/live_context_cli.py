from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .live_context import refresh_live_context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-live-context",
        description="Capture and audit starters, lineups, rosters, weather, and roof context.",
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument("--report-root", type=Path, default=Path("runtime/live_context"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = refresh_live_context(
        slate_date=args.date,
        snapshot_dir=args.snapshot_dir,
        report_root=args.report_root,
        captured_at=datetime.now(timezone.utc),
    )
    print(json.dumps(report.to_record(), indent=2, sort_keys=True))
    return 2 if report.status == "BLOCKED" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
