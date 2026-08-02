from __future__ import annotations

import pandas as pd

from supermodel.providers import PregameContext
from supermodel.series_context import (
    SERIES_CONTEXT_AUTHORITY,
    apply_series_context_policy,
    build_series_contexts,
)


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-07-29",
                "game_pk": 90,
                "team_a": "KC",
                "team_b": "TEX",
                "a_runs": 4,
                "b_runs": 2,
                "team_a_is_home": 1.0,
                "missing_home_away": 0.0,
            },
            {
                "date": "2026-07-30",
                "game_pk": 91,
                "team_a": "COL",
                "team_b": "LAD",
                "a_runs": 2,
                "b_runs": 5,
                "team_a_is_home": 1.0,
                "missing_home_away": 0.0,
            },
            {
                "date": "2026-07-31",
                "game_pk": 101,
                "team_a": "COL",
                "team_b": "KC",
                "a_runs": 3,
                "b_runs": 1,
                "team_a_is_home": 1.0,
                "missing_home_away": 0.0,
            },
            {
                "date": "2026-08-01",
                "game_pk": 102,
                "team_a": "COL",
                "team_b": "KC",
                "a_runs": 12,
                "b_runs": 6,
                "team_a_is_home": 1.0,
                "missing_home_away": 0.0,
            },
        ]
    )


def _context() -> PregameContext:
    return PregameContext(
        game_date="2026-08-02",
        away_team="KC",
        home_team="COL",
        game_pk=103,
        away_bullpen_recent_pitches=131.0,
        home_bullpen_recent_pitches=83.0,
    )


def _evaluation(probability: float = 0.5359) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_pk": 103,
                "away_team": "KC",
                "home_team": "COL",
                "pick": "KC",
                "pick_probability": probability,
                "confidence_score": 0.55,
                "model_overlap": 6,
                "model_count": 7,
                "selection_status": "ELIGIBLE",
                "selection_reasons": "",
                "selection_reason_count": 0,
                "eligible_for_top_pick": True,
                "is_top_pick": True,
            }
        ]
    )


def test_build_series_context_reconstructs_current_series_only():
    context = _context()
    series = build_series_contexts(_history(), [context])[103]

    assert series.status == "COMPLETE"
    assert series.games_played == 2
    assert [game.game_pk for game in series.games] == [101, 102]
    assert series.away_wins == 0
    assert series.home_wins == 2
    assert series.away_runs == 7
    assert series.home_runs == 15
    assert series.away_run_differential == -8
    assert series.latest_loser == "KC"
    assert series.latest_margin == 6
    assert series.away_consecutive_losses == 2
    assert series.summary == "COL leads 2-0; COL +8 runs"
    assert series.probability_authority == SERIES_CONTEXT_AUTHORITY


def test_series_context_gate_turns_modest_kc_lean_into_pass_without_changing_probability():
    context = _context()
    contexts = {103: context}
    series = build_series_contexts(_history(), [context])
    original_probability = float(_evaluation().iloc[0]["pick_probability"])

    result = apply_series_context_policy(
        _evaluation(),
        series_contexts=series,
        pregame_contexts=contexts,
        top_n=5,
    ).iloc[0]

    assert result["pick_probability"] == original_probability
    assert result["series_context_conflict"]
    assert result["selection_status"] == "PASS — SERIES CONTEXT"
    assert not result["eligible_for_top_pick"]
    assert not result["is_top_pick"]
    assert result["series_context_pick_losses"] == 2
    assert result["series_context_pick_run_differential"] == -8
    assert result["series_context_bullpen_pitch_disadvantage"] == 48.0
    assert result["series_context_reasons"] == (
        "SERIES_TRAILING_MULTIPLE_GAMES;"
        "SERIES_NEGATIVE_RUN_DIFFERENTIAL;"
        "SERIES_LATEST_BLOWOUT_LOSS;"
        "BULLPEN_CARRYOVER_DISADVANTAGE"
    )


def test_series_context_gate_does_not_override_strong_model_probability():
    context = _context()
    result = apply_series_context_policy(
        _evaluation(probability=0.61),
        series_contexts=build_series_contexts(_history(), [context]),
        pregame_contexts={103: context},
        top_n=5,
    ).iloc[0]

    assert not result["series_context_conflict"]
    assert result["selection_status"] == "ELIGIBLE"
    assert result["eligible_for_top_pick"]


def test_series_opener_does_not_reuse_an_older_matchup():
    history = _history()
    context = PregameContext(
        game_date="2026-08-02",
        away_team="LAD",
        home_team="COL",
        game_pk=201,
    )
    series = build_series_contexts(history, [context])[201]

    # COL's latest completed games were against KC, so the July 30 LAD-COL game is a
    # prior series and must not be attached to the August 2 matchup.
    assert series.status == "SERIES_OPENER"
    assert series.games_played == 0
    assert series.summary.startswith("Series opener")
