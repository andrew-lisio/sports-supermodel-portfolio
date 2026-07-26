from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from supermodel.mlb_v2 import DEFAULT_EWM_ALPHA, build_future_features, build_pregame_features
from supermodel.model_contract import V23_FEATURE_CONTRACT, V24_CANDIDATE_FEATURE_CONTRACT
from supermodel.validation import ValidationWindow, run_matched_walk_forward


def _games(periods: int = 8) -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=periods, freq="D")
    a_runs = [6.0, 1.0, 4.0, 7.0, 2.0, 8.0, 3.0, 5.0][:periods]
    b_runs = [2.0, 5.0, 3.0, 1.0, 3.0, 2.0, 6.0, 4.0][:periods]
    return pd.DataFrame(
        {
            "date": dates,
            "team_a": ["AAA"] * periods,
            "team_b": ["BBB"] * periods,
            "a_runs": a_runs,
            "b_runs": b_runs,
            "a_win": [int(a > b) for a, b in zip(a_runs, b_runs, strict=True)],
            "a_starter": ["Starter A"] * periods,
            "b_starter": ["Starter B"] * periods,
        }
    )


def test_selected_and_baseline_contracts_are_distinct_and_frozen() -> None:
    assert V23_FEATURE_CONTRACT.recent_form_alpha == pytest.approx(0.18)
    assert V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha == pytest.approx(0.25)
    assert DEFAULT_EWM_ALPHA == pytest.approx(0.25)
    assert V23_FEATURE_CONTRACT.recent_form_windows == (5, 10, 20)
    assert V24_CANDIDATE_FEATURE_CONTRACT.recent_form_windows == (3, 5, 10, 20)


def test_default_historical_and_future_builders_use_selected_candidate_alpha() -> None:
    games = _games()
    default_historical = build_pregame_features(games)
    explicit_historical = build_pregame_features(
        games,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
    )
    pd.testing.assert_series_equal(
        default_historical["ewm_rf_diff"],
        explicit_historical["ewm_rf_diff"],
        check_names=False,
    )

    history = games.iloc[:-1].copy()
    target_date = games.iloc[-1]["date"]
    matchup = pd.DataFrame(
        [
            {
                "date": target_date,
                "away_team": "AAA",
                "home_team": "BBB",
                "away_starter": "Starter A",
                "home_starter": "Starter B",
                "game_pk": 999,
            }
        ]
    )
    default_future = build_future_features(history, matchup)
    explicit_future = build_future_features(
        history,
        matchup,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
    )
    assert default_future.iloc[0]["ewm_rf_diff"] == pytest.approx(
        explicit_future.iloc[0]["ewm_rf_diff"]
    )
    assert default_future.iloc[0]["ewm_ra_diff"] == pytest.approx(
        explicit_future.iloc[0]["ewm_ra_diff"]
    )


class _EchoModel:
    def fit(self, frame: pd.DataFrame) -> "_EchoModel":
        return self

    def predict_proba(self, frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        probability = np.clip(0.5 + 0.01 * frame["ewm_rf_diff"].to_numpy(), 0.01, 0.99)
        return probability, {"echo": probability}


def test_matched_validation_uses_separate_baseline_state_values() -> None:
    dates = pd.date_range("2026-04-01", periods=6, freq="D")
    common = pd.DataFrame(
        {
            "date": dates,
            "team_a": ["AAA"] * 6,
            "team_b": ["BBB"] * 6,
            "a_win": [1, 0, 1, 0, 1, 0],
            "a_runs": [5, 2, 4, 1, 6, 3],
            "b_runs": [2, 3, 1, 4, 2, 5],
        }
    )
    baseline = common.assign(ewm_rf_diff=1.0)
    candidate = common.assign(ewm_rf_diff=2.0, win3_diff=0.0)
    window = ValidationWindow(
        name="test",
        start=pd.Timestamp("2026-04-05"),
        end=pd.Timestamp("2026-04-06"),
        minimum_training_games=1,
    )
    predictions, _ = run_matched_walk_forward(
        candidate,
        [window],
        baseline_features=baseline,
        model_factory=_EchoModel,
    )
    assert predictions["baseline_probability"].tolist() == pytest.approx([0.51, 0.51])
    assert predictions["candidate_probability"].tolist() == pytest.approx([0.52, 0.52])
