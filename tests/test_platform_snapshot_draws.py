from __future__ import annotations

import numpy as np
import pandas as pd

from supermodel.mlb_v2 import (
    simulate_poisson_score_distribution,
    simulate_score_distribution,
)


def test_poisson_score_distribution_returns_draws_when_requested() -> None:
    result = simulate_poisson_score_distribution(
        4.5,
        4.0,
        250,
        np.random.default_rng(7),
        return_draws=True,
    )
    assert result["team_a_runs"].shape == (250,)
    assert result["team_b_runs"].shape == (250,)
    assert result["team_a_runs"].dtype == np.int16
    assert result["team_b_runs"].dtype == np.int16


def test_legacy_score_distribution_returns_draws_when_requested() -> None:
    row = pd.Series(
        {
            "rf10_diff": 0.2,
            "rf10_sum": 8.8,
            "ra10_diff": -0.1,
            "ra10_sum": 8.6,
        }
    )
    result = simulate_score_distribution(
        row,
        125,
        np.random.default_rng(11),
        return_draws=True,
    )
    assert len(result["team_a_runs"]) == 125
    assert len(result["team_b_runs"]) == 125
