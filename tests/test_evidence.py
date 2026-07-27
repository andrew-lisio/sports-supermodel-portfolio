from __future__ import annotations

import json
from pathlib import Path

import pytest

from supermodel.evidence import (
    EvidenceIntegrityError,
    ProspectiveEvidenceLedger,
    audit_prospective_evidence,
)


START = "2030-07-20T18:00:00Z"
CAPTURE = "2030-07-20T16:00:00Z"
CLOSE = "2030-07-20T17:59:00Z"
FINAL = "2030-07-20T21:00:00Z"
SNAPSHOT_HASH = "a" * 64
PROVENANCE = {
    "schedule": "mlb_stats_api:v1/schedule",
    "live_feed": "mlb_stats_api:v1.1/game/feed/live",
    "pitcher_stats": "mlb_stats_api:v1/people/stats:season",
    "market_input": "manual_csv",
}


def _append_complete_game(path: Path) -> ProspectiveEvidenceLedger:
    ledger = ProspectiveEvidenceLedger(path)
    ledger.append(
        event_type="prediction",
        game_pk=900001,
        recorded_at=CAPTURE,
        scheduled_start=START,
        source="test",
        snapshot_sha256=SNAPSHOT_HASH,
        provenance=PROVENANCE,
        payload={
            "away_team": "AAA",
            "home_team": "BBB",
            "model_version": "2.4.0.dev9",
            "away_probability": 0.45,
            "home_probability": 0.55,
            "offered_home_implied": 0.52,
        },
    )
    ledger.append(
        event_type="closing_line",
        game_pk=900001,
        recorded_at=CLOSE,
        scheduled_start=START,
        source="test",
        payload={"closing_home_implied": 0.54},
    )
    ledger.append(
        event_type="outcome",
        game_pk=900001,
        recorded_at=FINAL,
        scheduled_start=START,
        source="test",
        payload={"home_won": 1},
    )
    return ledger


def test_complete_evidence_game_passes_non_holdout_gates(tmp_path: Path) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    _append_complete_game(ledger_path)

    report = audit_prospective_evidence(
        ledger_path,
        minimum_prospective_games=1,
    )

    gates = report["gate_evidence"]
    assert gates["prospective_games"]["status"] == "PASS"
    assert gates["prospective_games"]["observed"] == 1
    assert gates["closing_line_value_tracking"]["status"] == "PASS"
    assert gates["schedule_integrity_passed"]["status"] == "PASS"
    assert gates["target_leakage_tests_passed"]["status"] == "PASS"
    assert gates["point_in_time_provenance"]["status"] == "PASS"
    assert report["summary"]["brier"] == pytest.approx((0.55 - 1.0) ** 2)


def test_empty_ledger_keeps_release_evidence_pending(tmp_path: Path) -> None:
    report = audit_prospective_evidence(tmp_path / "missing.jsonl")
    gates = report["gate_evidence"]
    assert gates["prospective_games"]["status"] == "PENDING"
    assert gates["schedule_integrity_passed"]["status"] == "PENDING"
    assert gates["point_in_time_provenance"]["status"] == "PENDING"


def test_prediction_rejects_post_start_capture_and_target_field(tmp_path: Path) -> None:
    ledger = ProspectiveEvidenceLedger(tmp_path / "prospective.jsonl")
    with pytest.raises(EvidenceIntegrityError, match="after scheduled start"):
        ledger.append(
            event_type="prediction",
            game_pk=900001,
            recorded_at="2030-07-20T18:00:01Z",
            scheduled_start=START,
            source="test",
            snapshot_sha256=SNAPSHOT_HASH,
            provenance=PROVENANCE,
            payload={
                "away_team": "AAA",
                "home_team": "BBB",
                "model_version": "2.4.0.dev9",
                "home_probability": 0.55,
            },
        )

    with pytest.raises(EvidenceIntegrityError, match="outcome-like field"):
        ledger.append(
            event_type="prediction",
            game_pk=900001,
            recorded_at=CAPTURE,
            scheduled_start=START,
            source="test",
            snapshot_sha256=SNAPSHOT_HASH,
            provenance=PROVENANCE,
            payload={
                "away_team": "AAA",
                "home_team": "BBB",
                "model_version": "2.4.0.dev9",
                "home_probability": 0.55,
                "home_won": 1,
            },
        )


def test_hash_chain_tampering_is_detected(tmp_path: Path) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    ledger = _append_complete_game(ledger_path)
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["home_probability"] = 0.99
    lines[0] = json.dumps(event, sort_keys=True)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError, match="Event hash mismatch"):
        ledger.read(verify=True)

    report = audit_prospective_evidence(ledger_path, minimum_prospective_games=1)
    assert report["gate_evidence"]["prospective_games"]["status"] == "FAIL"
    assert report["issue_counts"]["ledger_integrity"] == 1


def test_missing_provenance_key_fails_provenance_gate(tmp_path: Path) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveEvidenceLedger(ledger_path)
    incomplete = dict(PROVENANCE)
    incomplete.pop("market_input")
    ledger.append(
        event_type="prediction",
        game_pk=900001,
        recorded_at=CAPTURE,
        scheduled_start=START,
        source="test",
        snapshot_sha256=SNAPSHOT_HASH,
        provenance=incomplete,
        payload={
            "away_team": "AAA",
            "home_team": "BBB",
            "model_version": "2.4.0.dev9",
            "home_probability": 0.55,
        },
    )
    report = audit_prospective_evidence(ledger_path, minimum_prospective_games=1)
    assert report["gate_evidence"]["point_in_time_provenance"]["status"] == "FAIL"
