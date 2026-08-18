from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from supermodel.pa_simulator import (
    PAGameInputs,
    hitter_profile_from_mlb_payload,
    load_pa_priors,
    matchup_event_probabilities,
    pitcher_profile_from_mlb_payload,
    simulate_pa_games,
)


def _hitting_payload(*, pa: int = 500, hits: int = 130, doubles: int = 28, triples: int = 3,
                     hr: int = 24, bb: int = 50, hbp: int = 5, k: int = 120) -> dict:
    return {
        "stats": [{"splits": [{"stat": {
            "plateAppearances": pa,
            "hits": hits,
            "doubles": doubles,
            "triples": triples,
            "homeRuns": hr,
            "baseOnBalls": bb,
            "hitByPitch": hbp,
            "strikeOuts": k,
        }}]}]
    }


def _pitching_payload(*, bf: int = 700, hits: int = 150, hr: int = 20,
                      bb: int = 55, hbp: int = 5, k: int = 180) -> dict:
    return {
        "stats": [{"splits": [{"stat": {
            "battersFaced": bf,
            "hits": hits,
            "homeRuns": hr,
            "baseOnBalls": bb,
            "hitBatsmen": hbp,
            "strikeOuts": k,
        }}]}]
    }


def _inputs() -> PAGameInputs:
    priors = load_pa_priors()
    batter = hitter_profile_from_mlb_payload(_hitting_payload(), prior=priors.event_probabilities)
    starter = pitcher_profile_from_mlb_payload(_pitching_payload(), prior=priors.event_probabilities)
    bullpen = pitcher_profile_from_mlb_payload(
        _pitching_payload(bf=2500, hits=560, hr=75, bb=205, hbp=22, k=640),
        prior=priors.event_probabilities,
    )
    return PAGameInputs(
        away_team="AWY",
        home_team="HOM",
        away_lineup=(batter,) * 9,
        home_lineup=(batter,) * 9,
        away_starter=starter,
        home_starter=starter,
        away_bullpen=bullpen,
        home_bullpen=bullpen,
        away_starter_expected_batters=21.0,
        home_starter_expected_batters=21.0,
    )


def test_priors_cover_all_base_out_event_states():
    priors = load_pa_priors()
    assert len(priors.transitions) == 3 * 8 * 9
    assert np.isclose(priors.event_probabilities.sum(), 1.0)
    assert np.all(priors.event_probabilities > 0)


def test_mlb_profiles_are_normalized_by_posterior_and_matchup():
    priors = load_pa_priors()
    batter = hitter_profile_from_mlb_payload(_hitting_payload(), prior=priors.event_probabilities)
    pitcher = pitcher_profile_from_mlb_payload(_pitching_payload(), prior=priors.event_probabilities)
    probabilities = matchup_event_probabilities(
        batter,
        pitcher,
        league_prior=priors.event_probabilities,
        pitcher_prior_strength=90.0,
        batting_home=False,
    )
    assert probabilities.shape == (9,)
    assert np.isclose(probabilities.sum(), 1.0)
    assert np.all(probabilities > 0)


def test_complete_pa_simulation_is_reproducible_and_score_is_downstream():
    inputs = _inputs()
    first = simulate_pa_games(inputs, 2000, seed=12345, return_draws=True)
    second = simulate_pa_games(inputs, 2000, seed=12345, return_draws=True)
    assert first.away_runs is not None and first.home_runs is not None
    assert second.away_runs is not None and second.home_runs is not None
    np.testing.assert_array_equal(first.away_runs, second.away_runs)
    np.testing.assert_array_equal(first.home_runs, second.home_runs)
    assert not np.any(first.away_runs == first.home_runs)
    assert np.isclose(first.away_win_probability + first.home_win_probability, 1.0)
    # No projected-score or expected-run input exists in PAGameInputs; the score means
    # emerge from completed PA sequences and should be plausible MLB values.
    assert 2.0 < first.mean_away_runs < 8.0
    assert 2.0 < first.mean_home_runs < 8.0
    assert 0.0 < first.extra_innings_probability < 0.25


def test_packaged_prior_resource_is_valid_json():
    path = Path(__file__).parents[1] / "src" / "supermodel" / "resources" / "pa_priors_2024.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["plate_appearances"] == 182449
    assert payload["transition_keys"] == 216
