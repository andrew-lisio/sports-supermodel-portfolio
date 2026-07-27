from __future__ import annotations

from collections import OrderedDict

import numpy as np
import pandas as pd

from supermodel import execution
from supermodel.execution import ExecutionProfile, resolve_execution_plan
from supermodel.mlb_v2 import V2Ensemble
from supermodel.model_registry import (
    EXPECTED_MODEL_COUNT,
    MODEL_ORDER,
    registry_snapshot,
    validate_runtime_models,
)
from supermodel.validation import ValidationWindow, run_matched_walk_forward


class _DeterministicComponent:
    def __init__(self, offset: float) -> None:
        self.offset = offset

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_DeterministicComponent":
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        signal = X["pyth_diff"].to_numpy(dtype=float)
        p = np.clip(0.5 + 0.04 * signal + self.offset, 0.05, 0.95)
        return np.column_stack([1.0 - p, p])


def _synthetic_features(rows: int = 180) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    pyth = np.sin(index / 7.0)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=rows, freq="D"),
            "team_a": ["AAA"] * rows,
            "team_b": ["BBB"] * rows,
            "a_runs": 4.0 + (index % 4),
            "b_runs": 3.0 + (index % 3),
            "a_win": (index.astype(int) % 2).astype(int),
            "a_starter": ["A"] * rows,
            "b_starter": ["B"] * rows,
            "pyth_diff": pyth,
            "win_pct_diff": np.cos(index / 9.0),
            "win10_diff": np.sin(index / 11.0),
            "starter_team_win_pct_diff": np.cos(index / 13.0),
            "starter_team_ra_diff": np.sin(index / 15.0),
            "rest_days_diff": (index % 3) - 1.0,
            "games_last3_diff": (index % 5) - 2.0,
            "ewm_win_diff": np.cos(index / 17.0),
        }
    )


def _dummy_ensemble(model_workers: int) -> V2Ensemble:
    ensemble = object.__new__(V2Ensemble)
    ensemble.model_workers = model_workers
    ensemble.estimator_threads = 1
    ensemble.models = OrderedDict(
        (name, _DeterministicComponent((position - 3) * 0.002))
        for position, name in enumerate(MODEL_ORDER)
    )
    ensemble.feature_names = []
    ensemble.feature_groups = {}
    ensemble.feature_reference_values = {}
    ensemble.weights = {}
    ensemble.calibrator = None
    ensemble.v1_anchor_weight = 0.25
    return ensemble


def test_registry_contains_exactly_seven_models_in_stable_order() -> None:
    models = OrderedDict((name, object()) for name in MODEL_ORDER)
    validate_runtime_models(models)
    snapshot = registry_snapshot()
    assert EXPECTED_MODEL_COUNT == 7
    assert snapshot["expected_model_count"] == 7
    assert tuple(snapshot["model_order"]) == MODEL_ORDER


def test_execution_plan_splits_validation_and_experiment_budgets(monkeypatch) -> None:
    monkeypatch.setattr(execution, "available_cpu_count", lambda: 8)
    profile = ExecutionProfile(
        name="accelerated",
        total_workers="auto",
        max_model_workers=7,
        comparison_workers=2,
        max_candidate_workers=2,
        estimator_threads=1,
    )
    validation = resolve_execution_plan(profile, workload="validation")
    experiment = resolve_execution_plan(profile, workload="experiment", candidate_count=5)
    assert validation.total_workers == 8
    assert validation.comparison_workers == 2
    assert validation.model_workers == 4
    assert experiment.candidate_workers == 2
    assert experiment.model_workers == 4


def test_parallel_ensemble_matches_serial_probabilities() -> None:
    features = _synthetic_features()
    train = features.iloc[:150]
    validation = features.iloc[150:]
    serial = _dummy_ensemble(1).fit(train)
    parallel = _dummy_ensemble(7).fit(train)
    serial_probability, serial_components = serial.predict_proba(validation)
    parallel_probability, parallel_components = parallel.predict_proba(validation)
    np.testing.assert_allclose(parallel_probability, serial_probability, atol=1e-12)
    assert tuple(parallel_components) == MODEL_ORDER
    for name in MODEL_ORDER:
        np.testing.assert_allclose(
            parallel_components[name], serial_components[name], atol=1e-12
        )


class _EchoModel:
    def fit(self, frame: pd.DataFrame) -> "_EchoModel":
        return self

    def predict_proba(self, frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        probability = np.clip(0.5 + 0.01 * frame["pyth_diff"].to_numpy(), 0.01, 0.99)
        return probability, {"echo": probability}


def test_parallel_matched_validation_matches_serial() -> None:
    features = _synthetic_features(170)
    window = ValidationWindow(
        name="parallel-check",
        start=pd.Timestamp("2026-05-31"),
        end=pd.Timestamp("2026-06-19"),
        minimum_training_games=100,
    )
    serial_predictions, _ = run_matched_walk_forward(
        features,
        [window],
        model_factory=_EchoModel,
        comparison_workers=1,
    )
    parallel_predictions, folds = run_matched_walk_forward(
        features,
        [window],
        model_factory=_EchoModel,
        comparison_workers=2,
    )
    pd.testing.assert_series_equal(
        parallel_predictions["baseline_probability"],
        serial_predictions["baseline_probability"],
    )
    pd.testing.assert_series_equal(
        parallel_predictions["candidate_probability"],
        serial_predictions["candidate_probability"],
    )
    assert folds.iloc[0]["fold_wall_seconds"] >= 0.0
