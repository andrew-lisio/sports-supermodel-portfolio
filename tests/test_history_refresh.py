from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from supermodel.game_registry import ImmutableSnapshotStore
from supermodel.history_refresh import (
    HistoryFreshnessError,
    parse_completed_schedule_games,
    refresh_completed_history,
)


def _game(
    game_pk: int,
    date: str,
    *,
    away: str = "AAA",
    home: str = "BBB",
    away_score: int = 5,
    home_score: int = 3,
    abstract: str = "Final",
    detailed: str = "Final",
) -> dict:
    return {
        "gamePk": game_pk,
        "officialDate": date,
        "gameDate": f"{date}T23:00:00Z",
        "doubleHeader": "N",
        "status": {
            "abstractGameState": abstract,
            "detailedState": detailed,
            "codedGameState": "F" if abstract == "Final" else "I",
        },
        "venue": {"id": 1, "name": "Test Park"},
        "teams": {
            "away": {
                "team": {"id": 1, "name": f"{away} Team", "abbreviation": away},
                "score": away_score,
                "probablePitcher": {"id": 11, "fullName": "Away Starter"},
            },
            "home": {
                "team": {"id": 2, "name": f"{home} Team", "abbreviation": home},
                "score": home_score,
                "probablePitcher": {"id": 22, "fullName": "Home Starter"},
            },
        },
    }


def _payload(*games: dict, date: str = "2026-07-20") -> dict:
    return {"dates": [{"date": date, "games": list(games)}]}


def _base_games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-19"),
                "game_pk": 100,
                "team_a": "AAA",
                "team_b": "CCC",
                "a_runs": 4.0,
                "b_runs": 2.0,
                "a_win": 1,
                "a_starter": "Starter A",
                "b_starter": "Starter C",
                "team_a_is_home": 0.0,
                "missing_home_away": 0.0,
            }
        ]
    )


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def completed_schedule_range(self, start_date: str, end_date: str) -> dict:
        self.calls.append((start_date, end_date))
        return self.payload


def test_parse_completed_schedule_games_prefers_final_duplicate():
    preview = _game(
        200,
        "2026-07-20",
        abstract="Preview",
        detailed="Scheduled",
    )
    final = _game(200, "2026-07-20", away_score=6, home_score=4)
    frame, blocking = parse_completed_schedule_games(
        {"dates": [{"date": "2026-07-20", "games": [preview, final]}]}
    )
    assert blocking == []
    assert len(frame) == 1
    assert int(frame.iloc[0].game_pk) == 200
    assert float(frame.iloc[0].a_runs) == 6.0
    assert frame.iloc[0].a_starter == "Away Starter"


def test_parse_completed_schedule_games_falls_back_to_linescore_runs():
    game = _game(823519, "2026-07-22", away="PIT", home="NYY", away_score=0, home_score=2)
    del game["teams"]["away"]["score"]
    del game["teams"]["home"]["score"]
    game["linescore"] = {
        "teams": {
            "away": {"runs": 0},
            "home": {"runs": 2},
        }
    }

    frame, blocking = parse_completed_schedule_games(
        {"dates": [{"date": "2026-07-22", "games": [game]}]}
    )

    assert blocking == []
    assert len(frame) == 1
    row = frame.iloc[0]
    assert int(row.game_pk) == 823519
    # Canonical alphabetical ordering keeps NYY as team_a and PIT as team_b.
    assert row.team_a == "NYY"
    assert float(row.a_runs) == 2.0
    assert float(row.b_runs) == 0.0
    assert int(row.a_win) == 1


def test_refresh_completed_history_persists_and_reuses_cache(tmp_path):
    client = FakeClient(_payload(_game(200, "2026-07-20")))
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    cache = tmp_path / "runtime" / "mlb_completed_games.csv"
    captured = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)

    merged, report = refresh_completed_history(
        _base_games(),
        slate_date="2026-07-21",
        client=client,
        snapshot_store=store,
        captured_at=captured,
        cache_path=cache,
    )
    assert report.status == "PASS"
    assert report.checked_through_date == "2026-07-20"
    assert report.backfilled_games == 1
    assert len(merged) == 2
    assert cache.exists()
    assert report.state_path.exists()
    assert client.calls == [("2026-07-20", "2026-07-20")]

    second_client = FakeClient({"dates": []})
    merged_again, second_report = refresh_completed_history(
        _base_games(),
        slate_date="2026-07-21",
        client=second_client,
        snapshot_store=store,
        captured_at=captured,
        cache_path=cache,
    )
    assert second_client.calls == []
    assert second_report.backfilled_games == 0
    assert len(merged_again) == 2


def test_refresh_filters_cache_after_requested_slate_date(tmp_path):
    client = FakeClient(
        {
            "dates": [
                {"date": "2026-07-20", "games": [_game(200, "2026-07-20")]},
                {"date": "2026-07-21", "games": [_game(201, "2026-07-21")]},
            ]
        }
    )
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    cache = tmp_path / "runtime" / "mlb_completed_games.csv"
    captured = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
    refresh_completed_history(
        _base_games(),
        slate_date="2026-07-22",
        client=client,
        snapshot_store=store,
        captured_at=captured,
        cache_path=cache,
    )
    older, report = refresh_completed_history(
        _base_games(),
        slate_date="2026-07-21",
        client=FakeClient({"dates": []}),
        snapshot_store=store,
        captured_at=captured,
        cache_path=cache,
    )
    assert report.checked_through_date == "2026-07-21"
    assert set(older["date"].dt.date.astype(str)) == {"2026-07-19", "2026-07-20"}


def test_refresh_fails_closed_on_network_error(tmp_path):
    class BrokenClient:
        def completed_schedule_range(self, start_date: str, end_date: str) -> dict:
            raise RuntimeError("offline")

    with pytest.raises(HistoryFreshnessError, match="refusing to evaluate with stale history"):
        refresh_completed_history(
            _base_games(),
            slate_date="2026-07-21",
            client=BrokenClient(),
            snapshot_store=ImmutableSnapshotStore(tmp_path / "snapshots"),
            captured_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
            cache_path=tmp_path / "cache.csv",
        )


def test_refresh_fails_closed_when_prior_game_is_still_live(tmp_path):
    live = _game(
        200,
        "2026-07-20",
        abstract="Live",
        detailed="In Progress",
    )
    with pytest.raises(HistoryFreshnessError, match="not final"):
        refresh_completed_history(
            _base_games(),
            slate_date="2026-07-21",
            client=FakeClient(_payload(live)),
            snapshot_store=ImmutableSnapshotStore(tmp_path / "snapshots"),
            captured_at=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
            cache_path=tmp_path / "cache.csv",
        )


def test_refresh_fetches_per_game_live_feed_when_range_schedule_omits_scores(tmp_path):
    game = _game(823519, "2026-07-20", away="PIT", home="NYY", away_score=0, home_score=2)
    del game["teams"]["away"]["score"]
    del game["teams"]["home"]["score"]

    class FallbackClient(FakeClient):
        def __init__(self):
            super().__init__(_payload(game))
            self.live_feed_calls: list[int] = []
            self.boxscore_calls: list[int] = []

        def live_feed(self, game_pk: int) -> dict:
            self.live_feed_calls.append(game_pk)
            return {
                "liveData": {
                    "linescore": {
                        "teams": {
                            "away": {"runs": 0},
                            "home": {"runs": 2},
                        }
                    }
                }
            }

        def boxscore(self, game_pk: int) -> dict:
            self.boxscore_calls.append(game_pk)
            raise AssertionError("boxscore should not be needed when live feed has scores")

    client = FallbackClient()
    cache = tmp_path / "runtime" / "mlb_completed_games.csv"
    merged, report = refresh_completed_history(
        _base_games(),
        slate_date="2026-07-21",
        client=client,
        snapshot_store=ImmutableSnapshotStore(tmp_path / "snapshots"),
        captured_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
        cache_path=cache,
    )

    assert report.status == "PASS"
    assert client.live_feed_calls == [823519]
    assert client.boxscore_calls == []
    row = merged.loc[merged["game_pk"] == 823519].iloc[0]
    assert row.team_a == "NYY"
    assert float(row.a_runs) == 2.0
    assert float(row.b_runs) == 0.0
    assert row.source == "mlb_stats_api_completed_schedule+per_game_score_fallback"
    fallback_snapshots = list(
        (tmp_path / "snapshots" / "mlb_completed_game_score_fallback").rglob("*.json")
    )
    assert len(fallback_snapshots) == 1


def test_refresh_uses_boxscore_when_live_feed_omits_scores(tmp_path):
    game = _game(823519, "2026-07-20", away="PIT", home="NYY", away_score=0, home_score=2)
    del game["teams"]["away"]["score"]
    del game["teams"]["home"]["score"]

    class FallbackClient(FakeClient):
        def __init__(self):
            super().__init__(_payload(game))
            self.calls_by_endpoint: list[str] = []

        def live_feed(self, game_pk: int) -> dict:
            self.calls_by_endpoint.append("live_feed")
            return {"liveData": {"linescore": {"teams": {}}}}

        def boxscore(self, game_pk: int) -> dict:
            self.calls_by_endpoint.append("boxscore")
            return {
                "teams": {
                    "away": {"teamStats": {"batting": {"runs": 0}}},
                    "home": {"teamStats": {"batting": {"runs": 2}}},
                }
            }

    client = FallbackClient()
    merged, report = refresh_completed_history(
        _base_games(),
        slate_date="2026-07-21",
        client=client,
        snapshot_store=ImmutableSnapshotStore(tmp_path / "snapshots"),
        captured_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
        cache_path=tmp_path / "cache.csv",
    )

    assert report.status == "PASS"
    assert client.calls_by_endpoint == ["live_feed", "boxscore"]
    row = merged.loc[merged["game_pk"] == 823519].iloc[0]
    assert float(row.a_runs) == 2.0
    assert float(row.b_runs) == 0.0
