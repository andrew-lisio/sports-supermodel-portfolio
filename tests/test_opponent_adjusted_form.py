from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from supermodel.feature_registry import feature_group_for
from supermodel.mlb_v2 import build_future_features, build_pregame_features
from supermodel.opponent_form import (
    OpponentAdjustedFormContract,
    apply_opponent_adjusted_contract,
    load_opponent_adjusted_experiment_plan,
    select_opponent_adjusted_candidate,
)


def _games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-04-01",
                "team_a": "BBB",
                "team_b": "CCC",
                "a_runs": 8.0,
                "b_runs": 1.0,
                "a_win": 1,
                "a_starter": "B1",
                "b_starter": "C1",
            },
            {
                "date": "2026-04-02",
                "team_a": "BBB",
                "team_b": "CCC",
                "a_runs": 7.0,
                "b_runs": 2.0,
                "a_win": 1,
                "a_starter": "B2",
                "b_starter": "C2",
            },
            {
                "date": "2026-04-03",
                "team_a": "AAA",
                "team_b": "BBB",
                "a_runs": 5.0,
                "b_runs": 4.0,
                "a_win": 1,
                "a_starter": "A1",
                "b_starter": "B3",
            },
            {
                "date": "2026-04-04",
                "team_a": "AAA",
                "team_b": "CCC",
                "a_runs": 3.0,
                "b_runs": 2.0,
                "a_win": 1,
                "a_starter": "A2",
                "b_starter": "C3",
            },
        ]
    ).assign(date=lambda frame: pd.to_datetime(frame["date"]))


def test_adjusted_features_are_optional_and_registered() -> None:
    plain = build_pregame_features(_games())
    adjusted = build_pregame_features(
        _games(), include_opponent_adjusted_recent_form=True
    )
    assert "opp_adj_win3_diff" not in plain
    assert "opp_adj_win3_diff" in adjusted
    assert feature_group_for("opp_adj_win3_diff") == "recent_form"
    assert feature_group_for("opp_adj_form_rd_momentum_diff") == "recent_form"


def test_target_result_cannot_change_its_own_adjusted_features() -> None:
    original = build_pregame_features(
        _games(), include_opponent_adjusted_recent_form=True
    )
    changed_games = _games()
    changed_games.loc[3, ["a_runs", "b_runs", "a_win"]] = [0.0, 20.0, 0]
    changed = build_pregame_features(
        changed_games, include_opponent_adjusted_recent_form=True
    )
    adjusted_columns = [
        column for column in original.columns if column.startswith("opp_adj_")
    ]
    assert adjusted_columns
    assert original.loc[3, adjusted_columns].tolist() == pytest.approx(
        changed.loc[3, adjusted_columns].tolist()
    )


def test_historical_and_future_adjusted_features_match() -> None:
    games = _games()
    historical = games.iloc[:3].copy()
    future_matchup = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-04-04")],
            "away_team": ["AAA"],
            "home_team": ["CCC"],
            "away_starter": ["A2"],
            "home_starter": ["C3"],
            "game_pk": [123],
        }
    )
    future = build_future_features(
        historical,
        future_matchup,
        include_opponent_adjusted_recent_form=True,
    )
    full = build_pregame_features(
        games, include_opponent_adjusted_recent_form=True
    )
    target = full.iloc[3]
    adjusted_columns = [
        column for column in future.columns if column.startswith("opp_adj_")
    ]
    assert adjusted_columns
    for column in adjusted_columns:
        assert future.iloc[0][column] == pytest.approx(target[column])


def test_contract_filters_adjusted_windows_and_momentum() -> None:
    features = build_pregame_features(
        _games(), include_opponent_adjusted_recent_form=True
    )
    contract = OpponentAdjustedFormContract(
        name="test",
        include_adjusted_form=True,
        windows=(5, 10, 20),
        include_momentum=False,
    )
    contracted = apply_opponent_adjusted_contract(features, contract)
    assert "opp_adj_win5_diff" in contracted
    assert "opp_adj_win3_diff" not in contracted
    assert "opp_adj_form_win_momentum_diff" not in contracted
    assert "win3_diff" in contracted


def test_plan_and_selection_can_retain_baseline(tmp_path: Path) -> None:
    path = tmp_path / "plan.yaml"
    path.write_text(
        """
        selection:
          minimum_log_loss_improvement: 0.0001
          minimum_brier_improvement: 0.0001
        candidates:
          - name: baseline
            baseline: true
            include_adjusted_form: false
            include_momentum: false
          - name: candidate
            include_adjusted_form: true
            include_momentum: false
            windows: [5, 10, 20]
        """,
        encoding="utf-8",
    )
    plan = load_opponent_adjusted_experiment_plan(path)
    summary = pd.DataFrame(
        [
            {
                "candidate": "baseline",
                "accuracy": 0.55,
                "brier": 0.249,
                "log_loss": 0.691,
                "auc": 0.56,
                "ece": 0.02,
                "opponent_adjusted_feature_count": 0,
            },
            {
                "candidate": "candidate",
                "accuracy": 0.55,
                "brier": 0.249,
                "log_loss": 0.691,
                "auc": 0.56,
                "ece": 0.02,
                "opponent_adjusted_feature_count": 12,
            },
        ]
    )
    selected = select_opponent_adjusted_candidate(summary, plan)
    assert selected["status"] == "baseline_retained"
    assert selected["selected"] == "baseline"
