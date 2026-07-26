from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from supermodel.mlb_v2 import build_pregame_features
from supermodel.recent_form import (
    RecentFormContract,
    apply_recent_form_contract,
    load_recent_form_experiment_plan,
    select_recent_form_candidate,
)


def _games() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-04-01", periods=5, freq="D"),
            "team_a": ["AAA"] * 5,
            "team_b": ["BBB"] * 5,
            "a_runs": [6.0, 1.0, 4.0, 7.0, 2.0],
            "b_runs": [2.0, 5.0, 3.0, 1.0, 3.0],
            "a_win": [1, 0, 1, 1, 0],
            "a_starter": ["Starter A"] * 5,
            "b_starter": ["Starter B"] * 5,
        }
    )


def test_recent_form_alpha_is_configurable_without_same_game_leakage() -> None:
    slow = build_pregame_features(_games(), recent_form_alpha=0.10)
    fast = build_pregame_features(_games(), recent_form_alpha=0.35)
    assert slow.iloc[1]["ewm_rf_diff"] != pytest.approx(fast.iloc[1]["ewm_rf_diff"])
    target_changed = _games()
    target_changed.loc[4, ["a_runs", "b_runs", "a_win"]] = [20.0, 0.0, 1]
    changed = build_pregame_features(target_changed, recent_form_alpha=0.35)
    assert fast.iloc[4]["ewm_rf_diff"] == pytest.approx(changed.iloc[4]["ewm_rf_diff"])


def test_contract_removes_only_unselected_recent_form_families() -> None:
    features = build_pregame_features(_games())
    contract = RecentFormContract(
        name="test",
        windows=(3, 10),
        include_momentum=False,
        include_ewm=True,
        include_last_game=False,
    )
    contracted = apply_recent_form_contract(features, contract)
    assert "win3_diff" in contracted
    assert "win10_diff" in contracted
    assert "win5_diff" not in contracted
    assert "form_rd_momentum_diff" not in contracted
    assert "last_win_diff" not in contracted
    assert "ewm_win_diff" in contracted
    assert "starter_team_ra_diff" in contracted


def test_experiment_plan_requires_one_baseline(tmp_path: Path) -> None:
    path = tmp_path / "plan.yaml"
    path.write_text(
        """
        candidates:
          - name: baseline
            baseline: true
            windows: [5, 10, 20]
            include_momentum: false
            ewm_alpha: 0.18
          - name: candidate
            windows: [3, 5, 10, 20]
            ewm_alpha: 0.25
        """,
        encoding="utf-8",
    )
    plan = load_recent_form_experiment_plan(path)
    assert plan.baseline.name == "baseline"
    assert plan.candidates[1].ewm_alpha == pytest.approx(0.25)


def test_selection_retains_baseline_when_improvement_is_too_small() -> None:
    from supermodel.recent_form import RecentFormExperimentPlan

    baseline = RecentFormContract(name="baseline", windows=(5, 10, 20), baseline=True)
    candidate = RecentFormContract(name="candidate")
    plan = RecentFormExperimentPlan(
        candidates=(baseline, candidate),
        minimum_log_loss_improvement=0.001,
        minimum_brier_improvement=0.001,
    )
    summary = pd.DataFrame(
        [
            {
                "candidate": "baseline",
                "accuracy": 0.55,
                "brier": 0.2500,
                "log_loss": 0.6900,
                "auc": 0.56,
                "ece": 0.04,
                "recent_form_feature_count": 20,
            },
            {
                "candidate": "candidate",
                "accuracy": 0.55,
                "brier": 0.2495,
                "log_loss": 0.6895,
                "auc": 0.56,
                "ece": 0.04,
                "recent_form_feature_count": 30,
            },
        ]
    )
    selection = select_recent_form_candidate(summary, plan)
    assert selection["selected"] == "baseline"
    assert selection["status"] == "baseline_retained"
