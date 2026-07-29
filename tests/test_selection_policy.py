from __future__ import annotations

import pandas as pd

from supermodel.selection_policy import apply_selection_policy


def _row(
    *,
    game_pk: int,
    away: str,
    home: str,
    pick: str,
    pick_probability: float,
    overlap: int,
    away_runs: float,
    home_runs: float,
    away_component_probabilities: list[float],
) -> dict:
    row = {
        "game_pk": game_pk,
        "away_team": away,
        "home_team": home,
        "pick": pick,
        "pick_probability": pick_probability,
        "model_overlap": overlap,
        "model_count": 7,
        "confidence_score": pick_probability,
        "simulated_away_runs": away_runs,
        "simulated_home_runs": home_runs,
    }
    row.update(
        {
            f"p_m{index}_{away}": value
            for index, value in enumerate(away_component_probabilities)
        }
    )
    return row


def test_conflicted_ensemble_is_preserved_but_removed_from_top_picks():
    conflicted = _row(
        game_pk=1,
        away="BAL",
        home="DET",
        pick="BAL",
        pick_probability=0.505,
        overlap=2,
        away_runs=4.1,
        home_runs=4.6,
        away_component_probabilities=[0.60, 0.55, 0.48, 0.47, 0.46, 0.45, 0.44],
    )
    eligible = _row(
        game_pk=2,
        away="SEA",
        home="TEX",
        pick="SEA",
        pick_probability=0.61,
        overlap=6,
        away_runs=5.2,
        home_runs=3.9,
        away_component_probabilities=[0.65, 0.60, 0.59, 0.58, 0.57, 0.56, 0.48],
    )
    result = apply_selection_policy(pd.DataFrame([conflicted, eligible]), top_n=1)

    baltimore = result.loc[result["game_pk"] == 1].iloc[0]
    assert baltimore["pick"] == "BAL"  # Raw prediction remains auditable.
    assert baltimore["component_consensus_pick"] == "DET"
    assert baltimore["projected_score_pick"] == "DET"
    assert baltimore["selection_status"] == "PASS"
    assert baltimore["selection_policy_version"] == "rc2-conflict-gate-v1"
    assert baltimore["selection_policy_mode"] == "PROVISIONAL_RECOMMENDATION_GATE"
    assert int(baltimore["selection_reason_count"]) >= 1
    assert "COMPONENT_CONSENSUS_CONFLICT" in baltimore["selection_reasons"]
    assert not bool(baltimore["is_top_pick"])

    seattle = result.loc[result["game_pk"] == 2].iloc[0]
    assert seattle["selection_status"] == "ELIGIBLE"
    assert int(seattle["selection_rank"]) == 1
    assert bool(seattle["is_top_pick"])
