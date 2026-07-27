from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adaptive_overlay import fit_adaptive_overlay, load_adaptive_overlay, overlay_training_frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fit or inspect the V2.4 prospective adaptive overlay")
    parser.add_argument("command", choices=("fit", "show", "training-data"))
    parser.add_argument("--ledger", type=Path, default=Path("runtime/evidence/prospective.jsonl"))
    parser.add_argument("--artifact", type=Path, default=Path("runtime/models/v2_4_adaptive_overlay.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fit":
        artifact = fit_adaptive_overlay(args.ledger, args.artifact)
        print(json.dumps(artifact.__dict__, indent=2, default=list))
        return 0
    if args.command == "show":
        artifact = load_adaptive_overlay(args.artifact)
        print(json.dumps(artifact.__dict__ if artifact else {"status": "MISSING"}, indent=2, default=list))
        return 0
    frame = overlay_training_frame(args.ledger)
    print(frame.to_json(orient="records", indent=2, date_format="iso"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
