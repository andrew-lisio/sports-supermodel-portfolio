from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .feature_authority import build_feature_authority_report, write_feature_authority_report
from .mlb_v2 import build_pregame_features, load_team_logs, reconstruct_games


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-features",
        description="Audit which collected MLB features are authorized to change predictions.",
    )
    parser.add_argument("command", choices=["audit"], nargs="?", default="audit")
    parser.add_argument("--data-dir", default="data/2026")
    parser.add_argument(
        "--output",
        default="reports/v2_4_feature_authority/feature_authority.json",
    )
    return parser


def run(args: argparse.Namespace) -> dict:
    games = reconstruct_games(load_team_logs(Path(args.data_dir)))
    historical_features = build_pregame_features(games)
    report = build_feature_authority_report(historical_features)
    write_feature_authority_report(args.output, report)
    return report


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    print(json.dumps(run(args), indent=2))


if __name__ == "__main__":
    main()
