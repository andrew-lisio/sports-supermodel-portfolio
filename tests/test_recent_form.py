from __future__ import annotations

import pandas as pd
import pytest

from supermodel.mlb_v2 import build_future_features, build_pregame_features


def _games(*, fourth_game_a_runs: float = 7.0, fourth_game_b_runs: float = 1.0) -> pd.DataFrame:
    rows = [
        ("2026-04-01", 6.0, 2.0),
        ("2026-04-02", 1.0, 5.0),
        ("2026-04-03", 4.0, 3.0),
        ("2026-04-04", fourth_game_a_runs, fourth_game_b_runs),
    ]
    return pd.DataFrame(
        {
            "date": pd.to_datetime([date for date, _, _ in rows]),
            "team_a": ["AAA"] * len(rows),
            "team_b": ["BBB"] * len(rows),
            "a_runs": [a_runs for _, a_runs, _ in rows],
            "b_runs": [b_runs for _, _, b_runs in rows],
            "a_win": [int(a_runs > b_runs) for _, a_runs, b_runs in rows],
            "a_starter": ["Starter A"] * len(rows),
            "b_starter": ["Starter B"] * len(rows),
        }
    )


def test_three_game_form_uses_only_completed_prior_games() -> None:
    features = build_pregame_features(_games())
    target = features.loc[features["date"] == pd.Timestamp("2026-04-04")].iloc[0]

    assert target["win3_diff"] == pytest.approx(1.0 / 3.0)
    assert target["rf3_diff"] == pytest.approx(1.0 / 3.0)
    assert target["rf3_sum"] == pytest.approx(7.0)
    assert target["ra3_diff"] == pytest.approx(-1.0 / 3.0)
    assert target["ra3_sum"] == pytest.approx(7.0)
    assert target["rd3_diff"] == pytest.approx(2.0 / 3.0)


def test_target_result_cannot_change_its_own_recent_form_features() -> None:
    a_wins = build_pregame_features(_games(fourth_game_a_runs=7.0, fourth_game_b_runs=1.0))
    b_wins = build_pregame_features(_games(fourth_game_a_runs=1.0, fourth_game_b_runs=7.0))
    columns = [
        "win3_diff",
        "rf3_diff",
        "rf3_sum",
        "ra3_diff",
        "ra3_sum",
        "rd3_diff",
        "form_win_momentum_diff",
        "form_rf_momentum_diff",
        "form_ra_momentum_diff",
        "form_rd_momentum_diff",
    ]

    a_target = a_wins.loc[a_wins["date"] == pd.Timestamp("2026-04-04"), columns]
    b_target = b_wins.loc[b_wins["date"] == pd.Timestamp("2026-04-04"), columns]
    pd.testing.assert_frame_equal(
        a_target.reset_index(drop=True),
        b_target.reset_index(drop=True),
    )


def test_future_builder_matches_historical_pregame_recent_form() -> None:
    games = _games()
    historical = games.iloc[:3].copy()
    matchup = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-04"),
                "away_team": "AAA",
                "home_team": "BBB",
                "away_starter": "Starter A",
                "home_starter": "Starter B",
                "game_pk": 123,
            }
        ]
    )

    historical_target = build_pregame_features(games).iloc[-1]
    future_target = build_future_features(historical, matchup).iloc[0]
    columns = [
        "win3_diff",
        "rf3_diff",
        "rf3_sum",
        "ra3_diff",
        "ra3_sum",
        "rd3_diff",
        "form_win_momentum_diff",
        "form_rf_momentum_diff",
        "form_ra_momentum_diff",
        "form_rd_momentum_diff",
    ]

    for column in columns:
        assert future_target[column] == pytest.approx(historical_target[column])
