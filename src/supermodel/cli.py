from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .game_registry import ImmutableSnapshotStore, parse_mlb_schedule
from .live_mlb import (
    LiveEvaluationConfig,
    MLBStatsHTTPClient,
    capture_live_slate,
    context_to_external_feature_record,
    contexts_to_matchups,
    evaluate_live_slate,
    evaluate_top_pick_parlays,
    load_manual_moneylines,
    write_evaluation_artifacts,
)
from .mlb_v2 import (
    attach_official_home_away,
    build_future_features,
    build_pregame_features,
    load_team_logs,
    reconstruct_games,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel",
        description=(
            "Capture public MLB pregame context, run the V2.3.1 ensemble and Poisson "
            "simulation, and rank a manually priced slate. No wager sizing is produced."
        ),
    )
    parser.add_argument("--date", required=True, help="Slate date in YYYY-MM-DD format")
    parser.add_argument("--odds", required=True, type=Path, help="Manual moneyline CSV")
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("snapshots"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/live"))
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


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, tuple[Path, Path | None, Path]]:
    moneylines = load_manual_moneylines(args.odds)

    client = MLBStatsHTTPClient()
    store = ImmutableSnapshotStore(args.snapshot_dir)
    _, _, contexts = capture_live_slate(
        game_date=args.date,
        client=client,
        snapshot_store=store,
        captured_at=datetime.now(timezone.utc),
    )

    odds_keys = {(line.away_team, line.home_team) for line in moneylines}
    contexts = [ctx for ctx in contexts if (ctx.away_team, ctx.home_team) in odds_keys]
    if len(contexts) != len(moneylines):
        captured = {(ctx.away_team, ctx.home_team) for ctx in contexts}
        missing = sorted(odds_keys.difference(captured))
        raise RuntimeError(f"Could not match all games to the official schedule: {missing}")

    logs = load_team_logs(args.data_dir)
    games = reconstruct_games(logs)
    history_start = pd.to_datetime(games["date"]).min().date().isoformat()
    history_end = (pd.Timestamp(args.date) - pd.Timedelta(days=1)).date().isoformat()
    history_schedule_payload = client.schedule_range(history_start, history_end)
    store.write_schedule(
        raw_payload=history_schedule_payload,
        captured_at=datetime.now(timezone.utc),
        source="mlb_stats_api:v1/schedule:historical_identity_backfill",
    )
    games = attach_official_home_away(games, parse_mlb_schedule(history_schedule_payload))
    historical_features = build_pregame_features(games)
    matchups = contexts_to_matchups(contexts)
    external = pd.DataFrame([context_to_external_feature_record(ctx) for ctx in contexts])
    future = build_future_features(games, matchups, external)

    evaluation = evaluate_live_slate(
        historical_features=historical_features,
        future_features=future,
        moneylines=moneylines,
        config=LiveEvaluationConfig(
            simulations=args.simulations,
            top_n=args.top_n,
            home_field_logit_adjustment=args.home_field_logit_adjustment,
        ),
    )
    parlays = None
    if not args.skip_parlays:
        parlays = evaluate_top_pick_parlays(evaluation, simulations=args.simulations)

    paths = write_evaluation_artifacts(
        evaluation,
        output_dir=args.output_dir,
        stem=f"mlb_v2_3_1_{args.date}",
        parlays=parlays,
    )
    return evaluation, paths


def main() -> None:
    args = build_parser().parse_args()
    evaluation, paths = run(args)
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
    print(evaluation[display_columns].to_string(index=False))
    print("\nArtifacts:")
    for path in paths:
        if path is not None:
            print(path)


if __name__ == "__main__":
    main()
