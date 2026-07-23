from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from supermodel.game_registry import ImmutableSnapshotStore
from supermodel.live_mlb import (
    LiveEvaluationConfig,
    ManualMoneyline,
    apply_pitcher_stats_to_context,
    capture_live_slate,
    enrich_context_from_live_feed,
    evaluate_live_slate,
    no_vig_probabilities,
    parse_pitcher_season_stats,
)
from supermodel.mlb_v2 import build_future_features
from supermodel.providers import PregameContext


def _historical_games() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "date": pd.Timestamp("2026-07-18"),
            "team_a": "AAA", "team_b": "BBB",
            "a_runs": 5.0, "b_runs": 3.0, "a_win": 1,
            "a_starter": "A One", "b_starter": "B One",
        },
        {
            "date": pd.Timestamp("2026-07-19"),
            "team_a": "AAA", "team_b": "CCC",
            "a_runs": 2.0, "b_runs": 4.0, "a_win": 0,
            "a_starter": "A Two", "b_starter": "C One",
        },
    ])


def test_build_future_features_preserves_away_home_and_canonical_orientation():
    matchups = pd.DataFrame([{
        "date": "2026-07-20",
        "game_pk": 123,
        "away_team": "CCC",
        "home_team": "AAA",
        "away_starter": "C Two",
        "home_starter": "A One",
        "lineups_confirmed": True,
    }])
    result = build_future_features(_historical_games(), matchups)
    row = result.iloc[0]
    assert row.team_a == "AAA"
    assert row.team_b == "CCC"
    assert row.a_starter == "A One"
    assert row.b_starter == "C Two"
    assert row.away_team == "CCC"
    assert row.home_team == "AAA"
    assert row.team_a_is_home == 1.0
    assert row.game_pk == 123
    # The immediately preceding game is represented explicitly, not only inside
    # rolling five-/ten-game averages. AAA lost 2-4 to CCC on July 19.
    assert row.last_win_diff == pytest.approx(-1.0)
    assert row.last_rf_diff == pytest.approx(-2.0)
    assert row.last_ra_diff == pytest.approx(2.0)
    assert row.last_rd_diff == pytest.approx(-4.0)
    assert row.last_rf_sum == pytest.approx(6.0)


def test_no_vig_probabilities_sum_to_one():
    away, home = no_vig_probabilities(+120, -130)
    assert np.isclose(away + home, 1.0)
    assert home > away


def test_live_feed_parser_extracts_lineups_pitchers_and_weather():
    context = PregameContext(game_date="2030-07-20", away_team="AAA", home_team="BBB")
    feed = {
        "gameData": {
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "probablePitchers": {
                "away": {"id": 11, "fullName": "Away Starter"},
                "home": {"id": 22, "fullName": "Home Starter"},
            },
            "weather": {"temp": "86", "condition": "Partly Cloudy", "wind": "9 mph, Out To CF"},
            "venue": {"roofType": "Open"},
            "players": {
                **{f"ID{i}": {"fullName": f"Away {i}"} for i in range(1, 10)},
                **{f"ID{i}": {"fullName": f"Home {i}"} for i in range(101, 110)},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"battingOrder": list(range(1, 10))},
                    "home": {"battingOrder": list(range(101, 110))},
                }
            }
        },
    }
    result = enrich_context_from_live_feed(context, feed)
    assert result.lineups_confirmed is True
    assert result.away_probable_pitcher_name == "Away Starter"
    assert result.home_probable_pitcher_name == "Home Starter"
    assert result.temperature_f == 86.0
    assert len(result.away_lineup_names) == 9
    assert len(result.home_lineup_names) == 9


def test_pitcher_stats_parser_and_context_mapping():
    payload = {
        "stats": [{"splits": [{"stat": {
            "inningsPitched": "100.0", "strikeOuts": 110, "baseOnBalls": 30,
            "hitBatsmen": 4, "homeRuns": 12, "battersFaced": 420,
            "era": "3.42", "whip": "1.18",
        }}]}]
    }
    parsed = parse_pitcher_season_stats(payload)
    assert parsed["starter_fip"] is not None
    assert parsed["starter_k_minus_bb"] is not None
    context = PregameContext(game_date="2030-07-20", away_team="AAA", home_team="BBB")
    apply_pitcher_stats_to_context(context, away_payload=payload, home_payload=payload)
    assert context.away_starter_era == 3.42
    assert context.home_starter_whip == 1.18


def test_capture_live_slate_writes_immutable_snapshots(tmp_path):
    schedule = {
        "dates": [{
            "date": "2030-07-20",
            "games": [{
                "gamePk": 999,
                "gameDate": "2030-07-20T23:05:00Z",
                "gameNumber": 1,
                "doubleHeader": "N",
                "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
                "teams": {
                    "away": {"team": {"id": 1, "name": "Away", "abbreviation": "AAA"},
                             "probablePitcher": {"id": 11, "fullName": "Away Starter"}},
                    "home": {"team": {"id": 2, "name": "Home", "abbreviation": "BBB"},
                             "probablePitcher": {"id": 22, "fullName": "Home Starter"}},
                },
                "venue": {"id": 10, "name": "Test Park"},
            }],
        }],
    }
    feed = {
        "gameData": {
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "probablePitchers": {
                "away": {"id": 11, "fullName": "Away Starter"},
                "home": {"id": 22, "fullName": "Home Starter"},
            },
            "players": {},
        },
        "liveData": {"boxscore": {"teams": {"away": {}, "home": {}}}},
    }

    class FakeClient:
        def schedule(self, game_date):
            return schedule
        def live_feed(self, game_pk):
            return feed
        def person_pitching_stats(self, person_id, season):
            return {"stats": []}

    store = ImmutableSnapshotStore(tmp_path)
    schedule_path, pregame_paths, contexts = capture_live_slate(
        game_date="2030-07-20",
        client=FakeClient(),
        snapshot_store=store,
        captured_at=datetime(2030, 7, 20, 20, 0, tzinfo=timezone.utc),
    )
    assert schedule_path.exists()
    assert len(pregame_paths) == 1 and pregame_paths[0].exists()
    assert contexts[0].game_pk == 999


def test_confidence_ranking_and_market_analysis_have_no_staking(monkeypatch):
    future = pd.DataFrame([
        {
            "date": pd.Timestamp("2026-07-20"), "game_pk": 1,
            "away_team": "AAA", "home_team": "BBB", "team_a": "AAA", "team_b": "BBB",
            "team_a_is_home": 0.0, "lineups_confirmed": True,
        },
        {
            "date": pd.Timestamp("2026-07-20"), "game_pk": 2,
            "away_team": "CCC", "home_team": "DDD", "team_a": "CCC", "team_b": "DDD",
            "team_a_is_home": 0.0, "lineups_confirmed": True,
        },
    ])

    class FakeModel:
        def fit(self, train):
            return self
        def predict_proba(self, target):
            comp = {f"m{i}": np.array([0.80, 0.60]) for i in range(7)}
            return np.array([0.80, 0.60]), comp
        def group_sensitivities(self, target):
            return {
                "offense": np.array([0.08, -0.03]),
                "starting_pitcher": np.array([-0.02, 0.05]),
            }

    class FakeScoreModel:
        def fit(self, train):
            return self
        def expected_runs(self, target):
            return np.array([5.5, 4.5]), np.array([3.0, 4.0])

    simulations = iter([
        {"team_a_win_probability": 0.80, "team_a_mean_runs": 5.5, "team_b_mean_runs": 3.0,
         "team_a_median_runs": 5.0, "team_b_median_runs": 3.0,
         "tie_rate_before_resolution": 0.1, "simulations": 1000.0},
        {"team_a_win_probability": 0.60, "team_a_mean_runs": 4.5, "team_b_mean_runs": 4.0,
         "team_a_median_runs": 4.0, "team_b_median_runs": 4.0,
         "tie_rate_before_resolution": 0.1, "simulations": 1000.0},
    ])
    monkeypatch.setattr("supermodel.live_mlb.V2Ensemble", FakeModel)
    monkeypatch.setattr("supermodel.live_mlb.PoissonScoreModel", FakeScoreModel)
    monkeypatch.setattr(
        "supermodel.live_mlb.simulate_poisson_score_distribution",
        lambda a, b, n, rng: next(simulations),
    )

    evaluations = evaluate_live_slate(
        historical_features=pd.DataFrame({"dummy": [1]}),
        future_features=future,
        moneylines=[
            ManualMoneyline("2026-07-20", "AAA", "BBB", -250, +210, 1),
            ManualMoneyline("2026-07-20", "CCC", "DDD", +150, -165, 2),
        ],
        config=LiveEvaluationConfig(simulations=1000, top_n=1),
    )
    assert evaluations.iloc[0].pick == "AAA"
    assert evaluations.iloc[0].pick_odds == -250
    assert evaluations.iloc[0].confidence_rank == 1
    assert evaluations.iloc[0].is_top_pick
    assert evaluations.iloc[0].fair_odds < 0
    assert evaluations.iloc[0].edge_vs_break_even == pytest.approx(evaluations.iloc[0].pick_probability - (250 / 350))
    assert evaluations.iloc[0].top_supporting_group == "offense"
    assert evaluations.iloc[0].top_supporting_sensitivity == pytest.approx(0.08)
    assert evaluations.iloc[0].top_opposing_group == "starting_pitcher"
    assert evaluations.iloc[0].top_opposing_sensitivity == pytest.approx(-0.02)
    assert evaluations.iloc[0].ensemble_pick_sensitivity_offense == pytest.approx(0.08)
    assert evaluations.iloc[0].attribution_scope == "seven_model_ensemble_before_score_blend"
    forbidden = {
        "stake_decision", "recommended_stake", "full_kelly_amount",
        "fractional_kelly_amount", "effective_bankroll", "staking_probability",
    }
    assert forbidden.isdisjoint(evaluations.columns)


def test_attach_official_home_away_and_excludes_ambiguous_doubleheader():
    from supermodel.game_registry import GameRecord
    from supermodel.mlb_v2 import attach_official_home_away

    games = pd.DataFrame([
        {"date": pd.Timestamp("2026-07-18"), "team_a": "AAA", "team_b": "BBB",
         "a_runs": 5, "b_runs": 3, "a_win": 1, "a_starter": "A", "b_starter": "B"},
        {"date": pd.Timestamp("2026-07-19"), "team_a": "AAA", "team_b": "CCC",
         "a_runs": 2, "b_runs": 4, "a_win": 0, "a_starter": "A", "b_starter": "C"},
    ])
    records = [
        GameRecord(1, "2026-07-18", "2026-07-18T23:00:00Z", 1, "N", "Final", "Final",
                   2, "BBB", "BBB", 1, "AAA", "AAA", 10, "Park", None, None, None, None),
        GameRecord(2, "2026-07-19", "2026-07-19T17:00:00Z", 1, "Y", "Final", "Final",
                   1, "AAA", "AAA", 3, "CCC", "CCC", 11, "Park 2", None, None, None, None),
        GameRecord(3, "2026-07-19", "2026-07-19T21:00:00Z", 2, "Y", "Final", "Final",
                   1, "AAA", "AAA", 3, "CCC", "CCC", 11, "Park 2", None, None, None, None),
    ]
    result = attach_official_home_away(games, records)
    assert len(result) == 1
    assert result.iloc[0].game_pk == 1
    assert result.iloc[0].team_a_is_home == 1.0
    assert result.iloc[0].missing_home_away == 0.0


def test_poisson_score_model_produces_positive_expected_runs():
    from supermodel.mlb_v2 import PoissonScoreModel

    rng = np.random.default_rng(7)
    n = 120
    frame = pd.DataFrame({
        "date": pd.date_range("2026-03-01", periods=n, freq="D"),
        "team_a": ["AAA"] * n,
        "team_b": ["BBB"] * n,
        "a_starter": ["A"] * n,
        "b_starter": ["B"] * n,
        "a_win": rng.binomial(1, 0.5, n),
        "a_runs": rng.poisson(4.7, n),
        "b_runs": rng.poisson(4.1, n),
        "form_diff": rng.normal(size=n),
        "team_a_is_home": rng.binomial(1, 0.5, n),
    })
    model = PoissonScoreModel().fit(frame)
    a, b = model.expected_runs(frame.iloc[:3])
    assert len(a) == 3 and len(b) == 3
    assert np.all(a > 0) and np.all(b > 0)
