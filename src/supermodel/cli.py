from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .odds_input import (
    collect_moneylines_interactively,
    load_moneylines,
    write_moneyline_template,
)
from .workflow import WorkflowResult, capture_official_slate, evaluate_captured_slate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel",
        description=(
            "Fetch an official MLB slate, accept user-entered two-way moneylines, run "
            "the V2.3.2 seven-model ensemble and Poisson simulation, and rank the games. "
            "No bankroll or wager sizing is produced."
        ),
    )
    parser.add_argument("--date", required=True, help="Slate date in YYYY-MM-DD format")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--odds",
        type=Path,
        help="Completed moneyline input in CSV or JSON format",
    )
    input_group.add_argument(
        "--interactive",
        action="store_true",
        help="Fetch the official slate and enter moneylines in the terminal",
    )
    input_group.add_argument(
        "--template",
        type=Path,
        help="Fetch the official slate, write a blank CSV/JSON odds template, and exit",
    )
    parser.add_argument(
        "--odds-format",
        choices=["american", "decimal"],
        default="american",
        help="Default input format for interactive entry or files without odds_format",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("runtime/snapshots"))
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/reports"))
    parser.add_argument("--simulations", type=int, default=100_000)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument(
        "--home-field-logit-adjustment",
        type=float,
        default=0.0,
        help="Experimental post-model adjustment; keep at zero unless independently validated.",
    )
    parser.add_argument(
        "--skip-parlays",
        action="store_true",
        help="Do not create the optional two-leg top-pick parlay comparison file.",
    )
    return parser


def run(args: argparse.Namespace) -> WorkflowResult | Path:
    captured = capture_official_slate(
        game_date=args.date,
        snapshot_dir=args.snapshot_dir,
    )

    if args.template is not None:
        return write_moneyline_template(captured.contexts, args.template)

    if args.interactive:
        moneylines = collect_moneylines_interactively(
            captured.contexts,
            odds_format=args.odds_format,
        )
        input_source = f"interactive_terminal:{args.odds_format}"
    else:
        moneylines = load_moneylines(
            args.odds,
            default_date=args.date,
            default_format=args.odds_format,
        )
        input_source = f"user_file:{Path(args.odds).suffix.lower().lstrip('.')}"

    return evaluate_captured_slate(
        captured_slate=captured,
        moneylines=moneylines,
        data_dir=args.data_dir,
        snapshot_dir=args.snapshot_dir,
        output_dir=args.output_dir,
        simulations=args.simulations,
        top_n=args.top_n,
        home_field_logit_adjustment=args.home_field_logit_adjustment,
        include_parlays=not args.skip_parlays,
        input_source=input_source,
    )


def _print_evaluation(evaluation: pd.DataFrame) -> None:
    display_columns = [
        "confidence_rank",
        "away_team",
        "home_team",
        "pick",
        "pick_odds",
        "pick_probability",
        "model_overlap",
        "model_count",
        "simulated_away_runs",
        "simulated_home_runs",
        "edge_vs_no_vig",
        "edge_vs_break_even",
        "fair_odds",
        "lineups_confirmed",
    ]
    available = [column for column in display_columns if column in evaluation.columns]
    print(evaluation[available].to_string(index=False))


def main() -> None:
    args = build_parser().parse_args()
    result = run(args)
    if isinstance(result, Path):
        print(f"Odds template written to: {result}")
        print("Fill both odds columns for the games you want to evaluate, then rerun with --odds.")
        return

    _print_evaluation(result.evaluation)
    print("\nArtifacts:")
    for path in [
        result.csv_path,
        result.parlay_path,
        result.json_path,
        result.market_snapshot_path,
    ]:
        if path is not None:
            print(path)


if __name__ == "__main__":
    main()
