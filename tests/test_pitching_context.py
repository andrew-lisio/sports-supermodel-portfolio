from __future__ import annotations

import pandas as pd

from supermodel.mlb_v2 import LIVE_FEATURES, build_pregame_features
from supermodel.pitching_context import build_pitching_context_rows


def _player(pid: int, *, ip: str, pitches: int, k: int, bb: int, hr: int = 0, save: int = 0):
    return {
        "person": {"id": pid},
        "stats": {
            "pitching": {
                "inningsPitched": ip,
                "numberOfPitches": pitches,
                "strikeOuts": k,
                "baseOnBalls": bb,
                "hitBatsmen": 0,
                "homeRuns": hr,
                "battersFaced": max(1, int(float(ip.replace('.1', '.333').replace('.2', '.667')) * 4.3)),
                "saves": save,
                "gamesFinished": 1 if save else 0,
            }
        },
    }


def _feed(game_pk: int, day: str, away: str, home: str, *, away_starter: int, home_starter: int,
          away_reliever: int, home_reliever: int, away_relief_pitches: int = 15,
          home_relief_pitches: int = 15):
    return {
        "gameData": {
            "game": {"pk": game_pk},
            "datetime": {"officialDate": day},
            "teams": {
                "away": {"abbreviation": away},
                "home": {"abbreviation": home},
            },
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {
                        "pitchers": [away_starter, away_reliever],
                        "players": {
                            f"ID{away_starter}": _player(away_starter, ip="6.0", pitches=90, k=7, bb=2),
                            f"ID{away_reliever}": _player(away_reliever, ip="1.0", pitches=away_relief_pitches, k=1, bb=0, save=1),
                        },
                    },
                    "home": {
                        "pitchers": [home_starter, home_reliever],
                        "players": {
                            f"ID{home_starter}": _player(home_starter, ip="5.0", pitches=85, k=4, bb=3, hr=1),
                            f"ID{home_reliever}": _player(home_reliever, ip="1.0", pitches=home_relief_pitches, k=1, bb=1, save=0),
                        },
                    },
                }
            }
        },
    }


def test_pitching_context_is_point_in_time_and_tracks_bullpen_workload():
    first = _feed(1, "2026-04-01", "AAA", "BBB", away_starter=10, home_starter=20,
                  away_reliever=11, home_reliever=21, away_relief_pitches=30)
    second = _feed(2, "2026-04-02", "AAA", "BBB", away_starter=10, home_starter=20,
                   away_reliever=11, home_reliever=21)
    frame = build_pitching_context_rows([first, second])

    assert list(frame["game_pk"]) == [1, 2]
    # The second game sees the first game's reliever usage; the first cannot see itself.
    assert float(frame.loc[0, "bullpen_fatigue_diff"]) == 0.0
    assert float(frame.loc[1, "bullpen_fatigue_diff"]) > 0.0
    assert float(frame.loc[1, "closer_available_diff"]) < 0.0
    # Starter state moves after the first observed outing.
    assert float(frame.loc[1, "starter_fip_diff"]) != float(frame.loc[0, "starter_fip_diff"])


def test_external_features_use_game_pk_for_doubleheaders_and_nan_is_missing():
    games = pd.DataFrame([
        {"date": pd.Timestamp("2026-04-01"), "game_pk": 1, "team_a": "AAA", "team_b": "BBB", "a_runs": 4, "b_runs": 3, "a_win": 1, "a_starter": "A", "b_starter": "B", "team_a_is_home": 0.0, "missing_home_away": 0.0},
        {"date": pd.Timestamp("2026-04-01"), "game_pk": 2, "team_a": "AAA", "team_b": "BBB", "a_runs": 2, "b_runs": 5, "a_win": 0, "a_starter": "C", "b_starter": "D", "team_a_is_home": 0.0, "missing_home_away": 0.0},
    ])
    external = pd.DataFrame([
        {"date": "2026-04-01", "game_pk": 1, "team_a": "AAA", "team_b": "BBB", "starter_fip_diff": 1.0},
        {"date": "2026-04-01", "game_pk": 2, "team_a": "AAA", "team_b": "BBB", "starter_fip_diff": float("nan")},
    ])
    features = build_pregame_features(games, external)
    assert float(features.loc[0, "live_starter_fip"]) == 1.0
    assert float(features.loc[0, "missing_starter_fip"]) == 0.0
    assert float(features.loc[1, "live_starter_fip"]) == 0.0
    assert float(features.loc[1, "missing_starter_fip"]) == 1.0
    assert set(LIVE_FEATURES).issuperset({"starter_fip", "bullpen_fatigue"})


def test_schedule_game_pks_excludes_abstract_final_postponed_placeholder():
    from supermodel.pitching_context import schedule_game_pks

    payload = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 823539,
                        "status": {
                            "abstractGameState": "Final",
                            "detailedState": "Postponed",
                            "codedGameState": "P",
                        },
                    },
                    {
                        "gamePk": 999,
                        "status": {
                            "abstractGameState": "Final",
                            "detailedState": "Final",
                            "codedGameState": "F",
                        },
                    },
                ]
            }
        ]
    }

    assert schedule_game_pks(payload) == [999]


def test_missing_pitcher_order_is_recovered_from_player_game_lines():
    feed = _feed(
        3,
        "2026-04-03",
        "AAA",
        "BBB",
        away_starter=30,
        home_starter=40,
        away_reliever=31,
        home_reliever=41,
    )
    away = feed["liveData"]["boxscore"]["teams"]["away"]
    away["players"]["ID30"]["stats"]["pitching"]["gamesStarted"] = 1
    del away["pitchers"]

    frame = build_pitching_context_rows([feed])

    assert list(frame["game_pk"]) == [3]


def test_fetch_pitching_context_uses_feed_cache(tmp_path):
    from supermodel.pitching_context import fetch_pitching_context

    feed = _feed(
        4,
        "2026-04-04",
        "AAA",
        "BBB",
        away_starter=50,
        home_starter=60,
        away_reliever=51,
        home_reliever=61,
    )
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 4,
                        "status": {
                            "abstractGameState": "Final",
                            "detailedState": "Final",
                            "codedGameState": "F",
                        },
                    }
                ]
            }
        ]
    }

    class Client:
        def __init__(self):
            self.feed_calls = 0

        def completed_schedule_range(self, start_date: str, end_date: str):
            return schedule

        def live_feed(self, game_pk: int):
            self.feed_calls += 1
            return feed

    first = Client()
    first_frame = fetch_pitching_context(
        first,
        start_date="2026-04-04",
        end_date="2026-04-04",
        cache_dir=tmp_path,
    )
    second = Client()
    second_frame = fetch_pitching_context(
        second,
        start_date="2026-04-04",
        end_date="2026-04-04",
        cache_dir=tmp_path,
    )

    assert first.feed_calls == 1
    assert second.feed_calls == 0
    assert list(first_frame["game_pk"]) == [4]
    assert list(second_frame["game_pk"]) == [4]


def test_fetch_pitching_context_skips_rescheduled_feed_outside_requested_range():
    from supermodel.pitching_context import fetch_pitching_context

    future_feed = _feed(
        823539,
        "2026-08-29",
        "BOS",
        "NYY",
        away_starter=70,
        home_starter=80,
        away_reliever=71,
        home_reliever=81,
    )
    schedule = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 823539,
                        "status": {
                            "abstractGameState": "Final",
                            "detailedState": "Final",
                            "codedGameState": "F",
                        },
                    }
                ]
            }
        ]
    }

    class Client:
        def completed_schedule_range(self, start_date: str, end_date: str):
            return schedule

        def live_feed(self, game_pk: int):
            return future_feed

    frame = fetch_pitching_context(
        Client(), start_date="2026-03-25", end_date="2026-07-28"
    )

    assert frame.empty
