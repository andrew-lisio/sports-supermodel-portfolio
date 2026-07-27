from __future__ import annotations

import pytest

from supermodel.odds_input import ManualMoneyline
from supermodel.providers import PregameContext
from supermodel.workflow import select_contexts_for_moneylines


def _context(game_pk: int, game_number: int) -> PregameContext:
    return PregameContext(
        game_date="2030-07-20",
        away_team="AAA",
        home_team="BBB",
        game_pk=game_pk,
        game_number=game_number,
        game_datetime=f"2030-07-20T{18 + game_number:02d}:00:00Z",
    )


def test_workflow_uses_game_pk_to_keep_doubleheaders_separate():
    contexts = [_context(101, 1), _context(102, 2)]
    line = ManualMoneyline("2030-07-20", "AAA", "BBB", 120, -130, 102)
    selected = select_contexts_for_moneylines(contexts, [line])
    assert selected[0].game_pk == 102


def test_workflow_rejects_ambiguous_doubleheader_without_game_pk():
    contexts = [_context(101, 1), _context(102, 2)]
    line = ManualMoneyline("2030-07-20", "AAA", "BBB", 120, -130, None)
    with pytest.raises(ValueError, match="doubleheader"):
        select_contexts_for_moneylines(contexts, [line])


def test_workflow_rejects_team_mismatch_for_game_pk():
    contexts = [_context(101, 1)]
    line = ManualMoneyline("2030-07-20", "CCC", "BBB", 120, -130, 101)
    with pytest.raises(ValueError, match="does not match"):
        select_contexts_for_moneylines(contexts, [line])


def test_workflow_records_prediction_evidence(tmp_path):
    from datetime import datetime, timezone
    import json

    import pandas as pd

    from supermodel.evidence import ProspectiveEvidenceLedger
    from supermodel.game_registry import ImmutableSnapshotStore
    from supermodel.workflow import record_prediction_evidence

    context = PregameContext(
        game_date="2030-07-20",
        away_team="AAA",
        home_team="BBB",
        game_pk=101,
        game_datetime="2030-07-20T18:00:00Z",
        provenance={
            "schedule": "schedule_source",
            "live_feed": "feed_source",
            "pitcher_stats": "pitcher_source",
        },
    )
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    pregame_path = store.write_pregame(
        game_pk=101,
        game_datetime=context.game_datetime,
        context_payload=context.to_record(),
        captured_at="2030-07-20T16:00:00Z",
        source="test",
    )
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps({"odds": [120, -130]}), encoding="utf-8")
    artifact_path = tmp_path / "prediction.json"
    artifact_path.write_text("[]", encoding="utf-8")
    evaluation = pd.DataFrame(
        [
            {
                "game_pk": 101,
                "away_probability": 0.44,
                "home_probability": 0.56,
                "model_overlap": 6,
                "model_count": 7,
            }
        ]
    )
    line = ManualMoneyline("2030-07-20", "AAA", "BBB", 120, -130, 101)
    ledger_path = tmp_path / "evidence.jsonl"

    returned = record_prediction_evidence(
        evaluation=evaluation,
        contexts=[context],
        moneylines=[line],
        pregame_paths=[pregame_path],
        market_snapshot_path=market_path,
        prediction_artifact=artifact_path,
        evidence_ledger=ledger_path,
        recorded_at=datetime(2030, 7, 20, 16, tzinfo=timezone.utc),
        input_source="test_market",
    )

    assert returned == ledger_path
    events = ProspectiveEvidenceLedger(ledger_path).read()
    assert len(events) == 1
    assert events[0]["event_type"] == "prediction"
    assert events[0]["payload"]["home_probability"] == 0.56
    assert events[0]["provenance"]["market_input"] == "test_market"
    assert len(events[0]["snapshot_sha256"]) == 64
