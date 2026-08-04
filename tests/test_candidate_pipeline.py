import numpy as np
import pandas as pd

from supermodel.candidate_pipeline import (
    PromotionThresholds,
    chronological_folds,
    evaluate_candidate_probabilities,
)


def test_candidate_report_never_auto_promotes_from_retrospective_data():
    rng = np.random.default_rng(7)
    outcomes = rng.binomial(1, 0.55, 600)
    baseline = np.full(600, 0.5)
    candidate = np.where(outcomes == 1, 0.58, 0.42)
    frame = pd.DataFrame(
        {
            "outcome": outcomes,
            "baseline_probability": baseline,
            "candidate_probability": candidate,
        }
    )
    report = evaluate_candidate_probabilities(
        frame,
        thresholds=PromotionThresholds(
            minimum_rows=500,
            minimum_probability_change=0.002,
            bootstrap_samples=200,
            maximum_ece_delta=1.0,
        ),
    )
    assert report.eligible_for_shadow
    assert not report.eligible_for_promotion
    assert report.candidate.brier < report.baseline.brier


def test_small_probability_change_fails_gate():
    frame = pd.DataFrame(
        {
            "outcome": [0, 1] * 300,
            "baseline_probability": [0.5] * 600,
            "candidate_probability": [0.5001] * 600,
        }
    )
    report = evaluate_candidate_probabilities(
        frame,
        thresholds=PromotionThresholds(bootstrap_samples=100),
    )
    assert report.gates["probability_change"]["status"] == "FAIL"
    assert not report.eligible_for_shadow


def test_chronological_folds_never_train_on_future_rows():
    frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=20)})
    folds = chronological_folds(frame, minimum_train_rows=10, fold_size=5)
    assert len(folds) == 2
    for train, test in folds:
        assert train.max() < test.min()
