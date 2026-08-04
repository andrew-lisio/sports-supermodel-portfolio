import json
from datetime import datetime, timezone

import numpy as np

from supermodel.public_views import game_analysis_records, load_performance_payload
from supermodel.simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot


def snapshot(track, away_probability):
    return SimulationSnapshot(
        game_pk=123,
        away_team="AWAY",
        home_team="HOME",
        model_track=track,
        model_version="test",
        git_commit="abc",
        input_snapshot_hash="hash",
        created_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        random_seed=1,
        away_runs=np.array([4, 5, 3, 6]),
        home_runs=np.array([3, 2, 4, 1]),
        away_win_probability=away_probability,
        home_win_probability=1 - away_probability,
        component_probabilities={"logistic": 0.6, "random_forest": 0.4},
        metadata={"game_date": "2026-08-04", "selection_status": "ELIGIBLE"},
    )


def test_game_analysis_combines_production_and_shadow(tmp_path):
    store = LocalSimulationSnapshotStore(tmp_path)
    store.save(snapshot("production", 0.60))
    store.save(snapshot("shadow", 0.58))
    records = game_analysis_records(event_date="2026-08-04", simulation_store_root=tmp_path)
    assert len(records) == 1
    assert abs(records[0]["production_shadow_delta"] + 0.02) < 1e-12
    assert records[0]["model_count"] == 2


def test_performance_payload_fails_closed(tmp_path):
    assert load_performance_payload(tmp_path / "missing.json") is None
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"summary": {"settled_games": 2}}), encoding="utf-8")
    assert load_performance_payload(path)["summary"]["settled_games"] == 2
