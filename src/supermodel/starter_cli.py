from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from .starter_features import export_starter_training_rows, write_starter_audit_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-starters",
        description="Audit and export immutable point-in-time starting-pitcher snapshots.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/starter_features.yaml"),
    )
    parser.add_argument("--snapshot-root", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="Validate starter snapshot integrity.")
    audit.add_argument("--output", type=Path, default=None)

    export = subparsers.add_parser(
        "export", help="Export the latest valid pregame starter row per game and side."
    )
    export.add_argument("--output", type=Path, default=None)
    return parser


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Starter feature config must be a YAML mapping")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _load_config(args.config)
    snapshot_root = args.snapshot_root or Path(
        str(config.get("snapshot_root", "runtime/snapshots"))
    )

    if args.command == "audit":
        output = args.output or Path(
            str(config.get("audit_report", "runtime/evidence/starter_snapshot_audit.json"))
        )
        report = write_starter_audit_report(snapshot_root, output)
        print(json.dumps(report, indent=2))
        return 1 if report["status"] == "FAIL" else 0

    output = args.output or Path(
        str(config.get("training_export", "runtime/evidence/starter_training_rows.csv"))
    )
    path = export_starter_training_rows(snapshot_root, output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
