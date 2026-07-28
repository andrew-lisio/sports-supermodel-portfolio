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
            "V2.3.3 as the production model and V2.4 as a versioned shadow candidate, "
            "and rank the production picks. No bankroll or wager sizing is produced."
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
    parser.add_argument(
        "--evidence-ledger",
        type=Path,
        default=Path("runtime/evidence/prospective.jsonl"),
        help="Append prediction evidence to this hash-chained JSONL ledger.",
    )
    parser.add_argument(
        "--history-cache",
        type=Path,
        default=Path("runtime/data/mlb_completed_games.csv"),
        help=(
            "Local cache of official completed games appended after the repository seed. "
            "The run fails closed if this cache cannot be refreshed through the prior day."
        ),
    )
    parser.add_argument(
        "--adaptive-overlay",
        type=Path,
        default=Path("runtime/models/v2_4_adaptive_overlay.json"),
        help=(
            "Versioned V2.4 shadow overlay artifact. It stays PENDING or INACTIVE until "
            "its chronological activation gate passes."
        ),
    )
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
        evidence_ledger=args.evidence_ledger,
        adaptive_overlay_path=args.adaptive_overlay,
        history_cache_path=args.history_cache,
        simulations=args.simulations,
        top_n=args.top_n,
        home_field_logit_adjustment=args.home_field_logit_adjustment,
        include_parlays=not args.skip_parlays,
        input_source=input_source,
    )


def _print_evaluation(evaluation: pd.DataFrame) -> None:
    display_columns = [
        "confidence_rank",
        "selection_rank",
        "selection_status",
        "selection_reasons",
        "away_team",
        "home_team",
        "pick",
        "pick_odds",
        "pick_probability",
        "model_overlap",
        "model_count",
        "shadow_pick",
        "shadow_pick_probability",
        "shadow_model_overlap",
        "production_shadow_disagree",
        "shadow_adaptive_overlay_status",
        "simulated_away_runs",
        "simulated_home_runs",
        "edge_vs_no_vig",
        "fair_odds",
        "lineups_confirmed",
        "history_freshness_status",
        "history_checked_through",
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
    refresh = result.history_refresh_report
    print(
        "\nHistory freshness: "
        f"{refresh.status}; checked through {refresh.checked_through_date}; "
        f"backfilled {refresh.backfilled_games} new games; "
        f"cache={refresh.cache_path}"
    )
    print("\nArtifacts:")
    for path in [
        result.csv_path,
        result.parlay_path,
        result.json_path,
        result.market_snapshot_path,
        result.evidence_ledger_path,
        result.adaptive_overlay_path,
    ]:
        if path is not None:
            print(path)


if __name__ == "__main__":
    main()
