from __future__ import annotations

import argparse
import json
from pathlib import Path

from .settlement import settle_ledger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-settle",
        description="Settle prospective predictions and write production/shadow performance.",
    )
    parser.add_argument("--ledger", type=Path, default=Path("runtime/evidence/prospective.jsonl"))
    parser.add_argument("--output-root", type=Path, default=Path("runtime/performance"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary, path = settle_ledger(args.ledger, output_root=args.output_root)
    print(json.dumps({"summary": summary.to_record(), "path": str(path)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
