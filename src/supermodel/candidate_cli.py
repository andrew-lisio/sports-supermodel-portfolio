from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .candidate_pipeline import evaluate_candidate_probabilities, write_candidate_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-candidate",
        description="Run paired chronological candidate probability gates.",
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("runtime/validation/candidate-report.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    frame = pd.read_csv(args.predictions)
    report = evaluate_candidate_probabilities(frame)
    path = write_candidate_report(report, args.output)
    print(json.dumps({"report": report.to_record(), "path": str(path)}, indent=2, sort_keys=True))
    return 0 if report.eligible_for_shadow else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
