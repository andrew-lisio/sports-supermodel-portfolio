from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from supermodel.evidence import ProspectiveEvidenceLedger, audit_prospective_evidence
from supermodel.game_registry import ImmutableSnapshotStore, ScheduleIntegrityError
from supermodel.live_mlb import capture_live_slate
from supermodel.starter_features import (
    audit_starter_snapshots,
    build_starter_snapshot_payload,
    latest_starter_training_rows,
    parse_innings_pitched,
    parse_pitcher_season_stats,
)


def _stats_payload(*, innings: str = "100.2", starts: int = 18) -> dict:
    return {
        "stats": [
            {
                "splits": [
                    {
                        "stat": {
                            "gamesPlayed": 19,
                            "gamesStarted": starts,
                            "inningsPitched": innings,
                            "strikeOuts": 110,
                            "baseOnBalls": 30,
                            "hitBatsmen": 4,
                            "homeRuns": 12,
                            "battersFaced": 420,
                            "hits": 91,
                            "earnedRuns": 38,
                            "groundOuts": 125,
                            "airOuts": 100,
                            "era": "3.42",
                            "whip": "1.18",
                        }
                    }
                ]
            }
        ]
    }


def _write_starter(
    store: ImmutableSnapshotStore,
    *,
    game_pk: int = 900001,
    side: str = "away",
    pitcher_id: int = 11,
    captured_at: str = "2030-07-20T16:00:00Z",
) -> Path:
    payload = build_starter_snapshot_payload(
        game_pk=game_pk,
        scheduled_start="2030-07-20T18:00:00Z",
        side=side,
        team_id=1 if side == "away" else 2,
        pitcher_id=pitcher_id,
        pitcher_name=f"Pitcher {pitcher_id}",
        season=2030,
        identity_source="test_schedule+feed",
        raw_payload=_stats_payload(),
    )
    return store.write_starter_pregame(
        game_pk=game_pk,
        game_datetime="2030-07-20T18:00:00Z",
        side=side,
        pitcher_id=pitcher_id,
        payload=payload,
        captured_at=captured_at,
        source="test_stats",
    )


def test_innings_parser_uses_baseball_out_notation() -> None:
    assert parse_innings_pitched("100.2") == pytest.approx(100 + 2 / 3)
    assert parse_innings_pitched("0.1") == pytest.approx(1 / 3)
    assert parse_innings_pitched("7.0") == 7.0
    assert parse_innings_pitched("12.3") is None


def test_pitcher_parser_exposes_point_in_time_rate_fields() -> None:
    parsed = parse_pitcher_season_stats(_stats_payload())
    assert parsed["available"] == 1.0
    assert parsed["games_started"] == 18.0
    assert parsed["season_innings"] == pytest.approx(100 + 2 / 3)
    assert parsed["starter_k_rate"] == pytest.approx(100 * 110 / 420)
    assert parsed["starter_bb_rate"] == pytest.approx(100 * 30 / 420)
    assert parsed["starter_k_minus_bb"] == pytest.approx(100 * 80 / 420)
    assert parsed["starter_ground_to_air"] == pytest.approx(1.25)
    assert parsed["starter_fip"] is not None


def test_starter_snapshot_fails_closed_after_start(tmp_path: Path) -> None:
    store = ImmutableSnapshotStore(tmp_path)
    payload = build_starter_snapshot_payload(
        game_pk=900001,
        scheduled_start="2030-07-20T18:00:00Z",
        side="away",
        team_id=1,
        pitcher_id=11,
        pitcher_name="Pitcher 11",
        season=2030,
        identity_source="test",
        raw_payload=_stats_payload(),
    )
    with pytest.raises(ScheduleIntegrityError, match="after game start"):
        store.write_starter_pregame(
            game_pk=900001,
            game_datetime="2030-07-20T18:00:00Z",
            side="away",
            pitcher_id=11,
            payload=payload,
            captured_at="2030-07-20T18:00:01Z",
            source="test",
        )


def test_starter_audit_detects_identity_change_and_exports_latest(tmp_path: Path) -> None:
    store = ImmutableSnapshotStore(tmp_path)
    first_path = _write_starter(
        store, pitcher_id=11, captured_at="2030-07-20T15:00:00Z"
    )
    assert ":" not in str(first_path.relative_to(tmp_path))
    _write_starter(store, pitcher_id=12, captured_at="2030-07-20T16:00:00Z")
    _write_starter(store, side="home", pitcher_id=22, captured_at="2030-07-20T16:00:00Z")

    report = audit_starter_snapshots(tmp_path)
    assert report["status"] == "PASS"
    assert report["summary"]["complete_two_starter_games"] == 1
    assert report["summary"]["identity_changes"] == 1
    assert report["identity_changes"][0]["pitcher_ids_in_capture_order"] == [11, 12]

    rows = latest_starter_training_rows(tmp_path)
    assert len(rows) == 2
    away = rows[rows["side"] == "away"].iloc[0]
    assert away.pitcher_id == 12
    assert away.starter_k_minus_bb == pytest.approx(100 * 80 / 420)


def test_starter_audit_detects_raw_payload_tampering(tmp_path: Path) -> None:
    store = ImmutableSnapshotStore(tmp_path)
    path = _write_starter(store)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["raw_payload"]["stats"][0]["splits"][0]["stat"][
        "strikeOuts"
    ] = 999
    path.write_text(json.dumps(envelope), encoding="utf-8")

    report = audit_starter_snapshots(tmp_path)
    assert report["status"] == "FAIL"
    assert report["issue_counts"]["payload"] >= 1


def test_live_capture_freezes_both_starter_payloads(tmp_path: Path) -> None:
    schedule = {
        "dates": [
            {
                "date": "2030-07-20",
                "games": [
                    {
                        "gamePk": 999,
                        "gameDate": "2030-07-20T23:05:00Z",
                        "gameNumber": 1,
                        "doubleHeader": "N",
                        "status": {
                            "abstractGameState": "Preview",
                            "detailedState": "Scheduled",
                        },
                        "teams": {
                            "away": {
                                "team": {"id": 1, "name": "Away", "abbreviation": "AAA"},
                                "probablePitcher": {"id": 11, "fullName": "Away Starter"},
                            },
                            "home": {
                                "team": {"id": 2, "name": "Home", "abbreviation": "BBB"},
                                "probablePitcher": {"id": 22, "fullName": "Home Starter"},
                            },
                        },
                        "venue": {"id": 10, "name": "Test Park"},
                    }
                ],
            }
        ]
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
            return _stats_payload()

    store = ImmutableSnapshotStore(tmp_path)
    _, pregame_paths, contexts = capture_live_slate(
        game_date="2030-07-20",
        client=FakeClient(),
        snapshot_store=store,
        captured_at=datetime(2030, 7, 20, 20, 0, tzinfo=timezone.utc),
    )
    context = contexts[0]
    assert len(pregame_paths) == 1
    assert context.away_starter_stats_snapshot_sha256
    assert context.home_starter_stats_snapshot_sha256
    assert Path(context.away_starter_stats_snapshot_path).exists()
    assert Path(context.home_starter_stats_snapshot_path).exists()
    assert context.away_starter_innings == pytest.approx(100 + 2 / 3)
    assert context.provenance["starter_stats_away"].startswith(
        "mlb_stats_api:v1/people/stats:season:sha256:"
    )


def test_evidence_audit_requires_snapshot_hash_for_supplied_starter_identity(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveEvidenceLedger(ledger_path)
    provenance = {
        "schedule": "schedule",
        "live_feed": "feed",
        "pitcher_stats": "stats",
        "starter_identity": "schedule+feed",
        "starter_stats_away": "snapshot",
        "starter_stats_home": "snapshot",
        "market_input": "manual",
    }
    ledger.append(
        event_type="prediction",
        game_pk=900001,
        recorded_at="2030-07-20T16:00:00Z",
        scheduled_start="2030-07-20T18:00:00Z",
        source="test",
        snapshot_sha256="a" * 64,
        provenance=provenance,
        payload={
            "away_team": "AAA",
            "home_team": "BBB",
            "model_version": "2.4.0.dev10",
            "home_probability": 0.55,
            "away_starter_id": 11,
            "home_starter_id": 22,
            "away_starter_snapshot_sha256": None,
            "home_starter_snapshot_sha256": "b" * 64,
        },
    )
    report = audit_prospective_evidence(
        ledger_path,
        minimum_prospective_games=1,
        required_provenance_keys=provenance.keys(),
    )
    assert report["gate_evidence"]["point_in_time_provenance"]["status"] == "FAIL"
    assert report["issue_counts"]["provenance"] >= 1


def test_empty_starter_snapshot_directory_audits_cleanly(tmp_path: Path) -> None:
    report = audit_starter_snapshots(tmp_path)
    assert report["status"] == "PENDING"
    assert report["summary"]["snapshot_files"] == 0
    assert latest_starter_training_rows(tmp_path).empty
