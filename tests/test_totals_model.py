import numpy as np
import pandas as pd

from supermodel.totals_model import (
    StarterWorkload,
    build_line_frontier,
    probability_for_line,
    simulate_totals_candidate,
    validate_probability_rows,
)


def test_candidate_preserves_means_and_has_positive_score_correlation():
    draws = simulate_totals_candidate(4.2, 4.8, simulations=80_000)
    assert abs(float(draws.away_runs.mean()) - 4.2) < 0.1
    assert abs(float(draws.home_runs.mean()) - 4.8) < 0.1
    assert np.corrcoef(draws.away_runs, draws.home_runs)[0, 1] > 0
    assert draws.status == "SHADOW_ONLY_NOT_PROMOTED"


def test_whole_total_has_push_probability_and_frontier():
    draws = simulate_totals_candidate(4.0, 4.0, simulations=30_000)
    over = probability_for_line(draws, market="game_total", line=8, selection="OVER")
    under = probability_for_line(draws, market="game_total", line=8, selection="UNDER")
    assert over.push > 0
    assert abs(over.win + over.push + under.win - 1.0) < 1e-9
    frontier = build_line_frontier(draws, lines=[8, 8.5])
    assert len(frontier) == 4


def test_expected_starter_innings_uses_workload_limits():
    workload = StarterWorkload(
        season_innings=100,
        games_started=20,
        rest_days=3,
        recent_pitch_count=110,
    )
    assert 4.0 <= workload.expected_innings() < 5.0


def test_validation_report_is_explicitly_sample_gated():
    frame = pd.DataFrame(
        {"over_probability": [0.6, 0.4, 0.7], "over_result": [1, 0, 1]}
    )
    report = validate_probability_rows(frame)
    assert report.status == "INSUFFICIENT_SAMPLE"
    assert report.rows == 3
