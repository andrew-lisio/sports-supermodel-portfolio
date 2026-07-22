from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from supermodel.game_registry import GameRecord, parse_mlb_schedule
from supermodel.mlb_v2 import (
    attach_official_home_away,
    build_pregame_features,
    load_team_logs,
    metric_row,
    reconstruct_games,
    walk_forward_operational_trials,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chronological V2.2 validation from a frozen schedule snapshot.")
    parser.add_argument("--schedule-snapshot", required=True, type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--simulations", type=int, default=10_000)
    return parser.parse_args()


def load_schedule_records(path: Path) -> list[GameRecord]:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document.get("payload", document)
    if payload.get("records"):
        return [GameRecord(**record) for record in payload["records"]]
    raw = payload.get("raw_payload", payload)
    return parse_mlb_schedule(raw)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = load_schedule_records(args.schedule_snapshot)
    games = reconstruct_games(load_team_logs(args.data_dir))
    games = attach_official_home_away(games, records)
    features = build_pregame_features(games)
    cutoff = features[features.date <= pd.Timestamp("2026-07-16")]
    predictions, folds = walk_forward_operational_trials(
        cutoff,
        simulations=args.simulations,
    )
    summary = {
        "v1": metric_row(predictions.a_win, predictions.v1_probability.to_numpy()),
        "v2": metric_row(predictions.a_win, predictions.v2_probability.to_numpy()),
        "v2_2": metric_row(predictions.a_win, predictions.v2_2_probability.to_numpy()),
        "score": metric_row(predictions.a_win, predictions.score_probability.to_numpy()),
        "score_simulations_per_game": args.simulations,
    }
    predictions.to_csv(args.output_dir / "v2_2_walk_forward_predictions.csv", index=False)
    folds.to_csv(args.output_dir / "v2_2_walk_forward_folds.csv", index=False)
    (args.output_dir / "v2_2_walk_forward_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
