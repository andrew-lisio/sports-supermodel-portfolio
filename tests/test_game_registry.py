from __future__ import annotations

import json
from pathlib import Path

import pytest

from supermodel.game_registry import (
    ImmutableSnapshotStore,
    ScheduleIntegrityError,
    parse_mlb_schedule,
)


def _doubleheader_payload() -> dict:
    def game(game_pk: int, game_number: int, game_date: str) -> dict:
        return {
            "gamePk": game_pk,
            "gameDate": game_date,
            "gameNumber": game_number,
            "doubleHeader": "Y",
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "venue": {"id": 12, "name": "Example Park"},
            "teams": {
                "away": {
                    "team": {"id": 111, "name": "Boston Red Sox", "abbreviation": "BOS"},
                    "probablePitcher": {"id": 501, "fullName": "Away Starter"},
                },
                "home": {
                    "team": {"id": 139, "name": "Tampa Bay Rays", "abbreviation": "TB"},
                    "probablePitcher": {"id": 601, "fullName": "Home Starter"},
                },
            },
        }

    return {
        "dates": [{
            "date": "2026-07-17",
            "games": [
                game(900001, 1, "2026-07-17T17:10:00Z"),
                game(900002, 2, "2026-07-17T23:10:00Z"),
            ],
        }]
    }


def test_game_pk_preserves_both_doubleheader_games():
    records = parse_mlb_schedule(_doubleheader_payload())
    assert [record.game_pk for record in records] == [900001, 900002]
    assert [record.game_number for record in records] == [1, 2]
    assert all(record.away_team_abbreviation == "BOS" for record in records)
    assert all(record.home_team_abbreviation == "TB" for record in records)


def test_conflicting_duplicate_game_pk_is_rejected():
    payload = _doubleheader_payload()
    duplicate = json.loads(json.dumps(payload["dates"][0]["games"][0]))
    duplicate["teams"]["home"]["team"]["name"] = "Conflicting Team"
    payload["dates"][0]["games"].append(duplicate)
    with pytest.raises(ScheduleIntegrityError, match="Conflicting records"):
        parse_mlb_schedule(payload)


def test_snapshot_store_is_immutable_and_idempotent(tmp_path: Path):
    store = ImmutableSnapshotStore(tmp_path)
    kwargs = {
        "raw_payload": _doubleheader_payload(),
        "captured_at": "2026-07-17T12:00:00-04:00",
        "source": "https://statsapi.mlb.com/api/v1/schedule",
    }
    first = store.write_schedule(**kwargs)
    second = store.write_schedule(**kwargs)
    assert first == second
    assert first.exists()

    envelope = store.read(first)
    assert envelope["captured_at"] == "2026-07-17T16:00:00Z"
    assert len(envelope["payload"]["records"]) == 2
    assert envelope["payload"]["records"][1]["game_pk"] == 900002


def test_pregame_snapshot_rejects_mismatched_game_pk(tmp_path: Path):
    store = ImmutableSnapshotStore(tmp_path)
    with pytest.raises(ScheduleIntegrityError, match="does not match"):
        store.write_pregame(
            game_pk=900001,
            game_datetime="2026-07-17T17:10:00Z",
            context_payload={"game_pk": 900002, "lineups_confirmed": False},
            captured_at="2026-07-17T15:00:00Z",
            source="manual-slate",
        )


def test_pregame_snapshot_is_keyed_by_game_pk(tmp_path: Path):
    store = ImmutableSnapshotStore(tmp_path)
    path = store.write_pregame(
        game_pk=900001,
        game_datetime="2026-07-17T17:10:00Z",
        context_payload={"lineups_confirmed": True, "home_current_implied": 0.56},
        captured_at="2026-07-17T15:00:00Z",
        source="manual-slate",
    )
    envelope = store.read(path)
    assert envelope["identity"] == "900001"
    assert envelope["payload"]["game_pk"] == 900001
    assert envelope["payload"]["lineups_confirmed"] is True


def test_pregame_snapshot_rejects_post_start_capture(tmp_path: Path):
    store = ImmutableSnapshotStore(tmp_path)
    with pytest.raises(ScheduleIntegrityError, match="after game start"):
        store.write_pregame(
            game_pk=900001,
            game_datetime="2026-07-17T17:10:00Z",
            context_payload={"lineups_confirmed": True},
            captured_at="2026-07-17T17:10:01Z",
            source="manual-slate",
        )
