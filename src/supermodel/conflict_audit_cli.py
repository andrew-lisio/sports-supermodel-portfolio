from __future__ import annotations

import argparse
import json
from pathlib import Path

from .conflict_audit import ConflictAuditConfig, write_conflict_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-conflicts",
        description=(
            "Audit whether the provisional conflict filter improves the quality of the "
            "surfaced recommendation set while preserving every raw prediction."
        ),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("runtime/evidence/prospective.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/evidence/conflict_filter_audit.json"),
    )
    parser.add_argument("--track", choices=["production", "shadow"], default="shadow")
    parser.add_argument("--minimum-graded-games", type=int, default=100)
    parser.add_argument("--minimum-filtered-games", type=int, default=40)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = write_conflict_audit(
        args.ledger,
        args.output,
        config=ConflictAuditConfig(
            track=args.track,
            minimum_graded_games=args.minimum_graded_games,
            minimum_filtered_games=args.minimum_filtered_games,
        ),
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
