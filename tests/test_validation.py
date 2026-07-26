from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from supermodel.validation import (
    V23_BASELINE_EXCLUDED_FEATURES,
    ValidationWindow,
    calibration_table,
    evaluate_promotion_gates,
    freeze_v23_feature_contract,
    load_validation_plan,
    paired_bootstrap_differences,
    probability_metrics,
    run_matched_walk_forward,
    subgroup_metrics,
)


def test_freeze_v23_feature_contract_removes_only_phase3_fields() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-01"]),
            "a_win": [1],
            "win3_diff": [0.5],
            "form_rd_momentum_diff": [1.2],
            "win10_diff": [0.2],
        }
    )
    frozen = freeze_v23_feature_contract(frame)
    assert "win3_diff" not in frozen
    assert "form_rd_momentum_diff" not in frozen
    assert "win10_diff" in frozen
    assert frame.columns.tolist() != frozen.columns.tolist()
    assert set(V23_BASELINE_EXCLUDED_FEATURES).issuperset(
        {"win3_diff", "form_rd_momentum_diff"}
    )


def test_probability_metrics_and_calibration_are_consistent() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    table = calibration_table(y, p, bins=2)
    metrics = probability_metrics(y, p, bins=2)
    assert table["n"].sum() == 4
    assert metrics["coverage"] == pytest.approx(1.0)
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["brier"] == pytest.approx(0.025)
    assert metrics["ece"] == pytest.approx(0.15)


def test_paired_bootstrap_is_deterministic_and_candidate_improves() -> None:
    y = np.array([0, 0, 1, 1, 1, 0])
    baseline = np.array([0.45, 0.55, 0.55, 0.45, 0.52, 0.48])
    candidate = np.array([0.10, 0.20, 0.80, 0.90, 0.75, 0.25])
    first = paired_bootstrap_differences(
        y, baseline, candidate, iterations=100, seed=7
    )
    second = paired_bootstrap_differences(
        y, baseline, candidate, iterations=100, seed=7
    )
    assert first == second
    assert first["brier"]["point"] < 0
    assert first["log_loss"]["point"] < 0
    assert first["accuracy"]["point"] > 0


class _FakeModel:
    def __init__(self) -> None:
        self.has_phase3 = False

    def fit(self, train: pd.DataFrame) -> "_FakeModel":
        self.has_phase3 = "win3_diff" in train.columns
        return self

    def predict_proba(self, validation: pd.DataFrame):
        if self.has_phase3:
            probability = np.where(validation["a_win"].to_numpy() == 1, 0.7, 0.3)
        else:
            probability = np.repeat(0.5, len(validation))
        components = {f"model_{index}": probability for index in range(7)}
        return probability, components


def _synthetic_features() -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=12, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "team_a": ["AAA"] * len(dates),
            "team_b": ["BBB"] * len(dates),
            "a_win": [index % 2 for index in range(len(dates))],
            "a_runs": [4.0] * len(dates),
            "b_runs": [3.0] * len(dates),
            "win3_diff": np.linspace(-0.5, 0.5, len(dates)),
            "win10_diff": np.linspace(-0.2, 0.2, len(dates)),
        }
    )


def test_matched_walk_forward_uses_same_games_for_baseline_and_candidate() -> None:
    window = ValidationWindow(
        name="test",
        start=pd.Timestamp("2026-04-07"),
        end=pd.Timestamp("2026-04-12"),
        minimum_training_games=5,
    )
    predictions, folds = run_matched_walk_forward(
        _synthetic_features(), [window], model_factory=_FakeModel, calibration_bins=3
    )
    assert len(predictions) == 6
    assert predictions["baseline_probability"].eq(0.5).all()
    assert set(predictions["candidate_probability"]) == {0.3, 0.7}
    assert folds.iloc[0]["status"] == "completed"
    assert folds.iloc[0]["candidate_brier"] < folds.iloc[0]["baseline_brier"]


def test_subgroup_report_contains_all_and_agreement_groups() -> None:
    predictions, _ = run_matched_walk_forward(
        _synthetic_features(),
        [
            ValidationWindow(
                name="test",
                start=pd.Timestamp("2026-04-07"),
                end=pd.Timestamp("2026-04-12"),
                minimum_training_games=5,
            )
        ],
        model_factory=_FakeModel,
        calibration_bins=3,
    )
    report = subgroup_metrics(predictions, minimum_games=1)
    assert ((report.dimension == "all") & (report.value == "all")).any()
    assert (report.dimension == "baseline_candidate").any()


def test_promotion_gates_distinguish_failures_from_pending_evidence() -> None:
    baseline = {
        "n": 1000,
        "accuracy": 0.55,
        "brier": 0.25,
        "log_loss": 0.69,
        "auc": 0.56,
        "ece": 0.04,
        "coverage": 1.0,
    }
    candidate = {
        "n": 1000,
        "accuracy": 0.56,
        "brier": 0.24,
        "log_loss": 0.68,
        "auc": 0.565,
        "ece": 0.035,
        "coverage": 1.0,
    }
    config = {
        "requirements": {
            "minimum_walk_forward_games": 1000,
            "brier_improvement_required": True,
            "log_loss_improvement_required": True,
            "auc_not_worse_by_more_than": 0.005,
            "accuracy_not_worse_by_more_than": 0.01,
            "ece_not_worse_by_more_than": 0.01,
            "coverage_not_worse_by_more_than": 0.01,
            "minimum_prospective_games": 500,
            "final_holdout_required": True,
        }
    }
    report = evaluate_promotion_gates(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        gate_config=config,
    )
    assert report["overall_status"] == "PENDING"
    statuses = {row["gate"]: row["status"] for row in report["gates"]}
    assert statuses["brier_improvement"] == "PASS"
    assert statuses["minimum_prospective_games"] == "PENDING"
    assert statuses["final_holdout_required"] == "PENDING"


def test_validation_plan_keeps_holdout_separate(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        """
        defaults:
          minimum_training_games: 10
        development_windows:
          - name: dev
            start: 2026-04-01
            end: 2026-04-10
        holdout:
          name: holdout
          start: 2026-04-11
          end: 2026-04-20
        """,
        encoding="utf-8",
    )
    plan = load_validation_plan(plan_path)
    assert len(plan.development_windows) == 1
    assert plan.development_windows[0].role == "development"
    assert plan.holdout_window is not None
    assert plan.holdout_window.role == "holdout"
