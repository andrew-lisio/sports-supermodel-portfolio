from __future__ import annotations

from pathlib import Path

import pytest

from supermodel.conflict_audit import ConflictAuditConfig, audit_conflict_filter
from supermodel.evidence import ProspectiveEvidenceLedger


START = "2030-07-20T18:00:00Z"
CAPTURE = "2030-07-20T16:00:00Z"
FINAL = "2030-07-20T21:00:00Z"
SNAPSHOT_HASH = "a" * 64
PROVENANCE = {
    "schedule": "test",
    "live_feed": "test",
    "pitcher_stats": "test",
    "market_input": "test",
}


def _append_game(
    ledger: ProspectiveEvidenceLedger,
    *,
    game_pk: int,
    home_probability: float,
    status: str,
    reasons: str,
    home_won: int,
) -> None:
    ledger.append(
        event_type="prediction",
        game_pk=game_pk,
        recorded_at=CAPTURE,
        scheduled_start=START,
        source="test",
        snapshot_sha256=SNAPSHOT_HASH,
        provenance=PROVENANCE,
        payload={
            "game_date": "2030-07-20",
            "away_team": "AAA",
            "home_team": "BBB",
            "model_version": "2.4.0.rc2.post1",
            "away_probability": 1.0 - home_probability,
            "home_probability": home_probability,
            "production_away_probability": 1.0 - home_probability,
            "production_home_probability": home_probability,
            "model_overlap": 3,
            "production_model_overlap": 3,
            "selection_status": status,
            "selection_reasons": reasons,
            "shadow_selection_status": status,
            "shadow_selection_reasons": reasons,
            "production_selection_status": status,
            "production_selection_reasons": reasons,
            "selection_policy_version": "rc2-conflict-gate-v1",
            "selection_policy_mode": "PROVISIONAL_RECOMMENDATION_GATE",
        },
    )
    ledger.append(
        event_type="outcome",
        game_pk=game_pk,
        recorded_at=FINAL,
        scheduled_start=START,
        source="test",
        payload={"home_won": home_won},
    )


def test_conflict_audit_separates_helpful_and_false_passes(tmp_path: Path) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveEvidenceLedger(ledger_path)
    _append_game(
        ledger,
        game_pk=1,
        home_probability=0.55,
        status="PASS",
        reasons="LOW_OVERLAP",
        home_won=0,
    )
    _append_game(
        ledger,
        game_pk=2,
        home_probability=0.55,
        status="PASS",
        reasons="LOW_PROBABILITY;PROJECTED_SCORE_CONFLICT",
        home_won=1,
    )
    _append_game(
        ledger,
        game_pk=3,
        home_probability=0.60,
        status="ELIGIBLE",
        reasons="",
        home_won=1,
    )

    report = audit_conflict_filter(
        ledger_path,
        config=ConflictAuditConfig(
            track="shadow", minimum_graded_games=3, minimum_filtered_games=2
        ),
    )

    summary = report["summary"]
    assert report["evidence_status"] == "READY_FOR_REVIEW"
    assert summary["graded_games"] == 3
    assert summary["filtered_games"] == 2
    assert summary["helpful_passes"] == 1
    assert summary["false_passes"] == 1
    assert summary["helpful_pass_rate"] == pytest.approx(0.5)
    assert summary["raw_accuracy"] == pytest.approx(2 / 3)
    assert summary["eligible_accuracy"] == pytest.approx(1.0)
    assert summary["coverage"] == pytest.approx(1 / 3)

    by_reason = {row["reason"]: row for row in report["reason_summary"]}
    assert by_reason["LOW_OVERLAP"]["helpful_pass_rate"] == pytest.approx(1.0)
    assert by_reason["LOW_PROBABILITY"]["helpful_pass_rate"] == pytest.approx(0.0)


def test_conflict_audit_is_pending_for_empty_ledger(tmp_path: Path) -> None:
    report = audit_conflict_filter(tmp_path / "missing.jsonl")
    assert report["evidence_status"] == "PENDING"
    assert report["summary"]["graded_games"] == 0


def test_conflict_audit_can_grade_production_track(tmp_path: Path) -> None:
    ledger_path = tmp_path / "prospective.jsonl"
    ledger = ProspectiveEvidenceLedger(ledger_path)
    _append_game(
        ledger,
        game_pk=1,
        home_probability=0.55,
        status="ELIGIBLE",
        reasons="",
        home_won=1,
    )
    report = audit_conflict_filter(
        ledger_path,
        config=ConflictAuditConfig(
            track="production", minimum_graded_games=1, minimum_filtered_games=1
        ),
    )
    assert report["summary"]["raw_accuracy"] == pytest.approx(1.0)
    assert report["track"] == "production"
