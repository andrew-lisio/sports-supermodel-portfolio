from datetime import datetime, timezone

import numpy as np
import pytest

from supermodel.market_schema import MarketQuote
from supermodel.simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot


def _snapshot() -> SimulationSnapshot:
    return SimulationSnapshot(
        game_pk=77,
        away_team="ATL",
        home_team="MIA",
        model_track="production",
        model_version="2.3.3",
        git_commit="abc123",
        input_snapshot_hash="input-hash",
        created_at=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
        random_seed=7,
        away_runs=np.array([5, 4, 3, 2], dtype=int),
        home_runs=np.array([3, 4, 5, 1], dtype=int),
    )


def _quote(**kwargs) -> MarketQuote:
    values = {
        "game_pk": 77,
        "sportsbook": "Book",
        "market_type": "moneyline",
        "selection": "ATL",
        "american_odds": -110,
        "captured_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
    }
    values.update(kwargs)
    return MarketQuote(**values)


def test_snapshot_prices_moneyline_spread_total_and_team_total():
    snapshot = _snapshot()
    assert snapshot.probability_for_quote(_quote()).win == pytest.approx(0.625)
    run_line = _quote(market_type="run_line", line=-1.5)
    assert snapshot.probability_for_quote(run_line).win == pytest.approx(0.25)
    total = _quote(market_type="game_total", selection="OVER", line=7.0)
    probability = snapshot.probability_for_quote(total)
    assert probability.win == pytest.approx(0.75)
    assert probability.push == pytest.approx(0.0)
    team_total = _quote(
        market_type="team_total", selection="OVER", team="ATL", line=3.5
    )
    assert snapshot.probability_for_quote(team_total).win == pytest.approx(0.5)


def test_local_snapshot_store_round_trip(tmp_path):
    store = LocalSimulationSnapshotStore(tmp_path)
    snapshot = _snapshot()
    manifest, arrays = store.save(snapshot)
    assert manifest.exists() and arrays.exists()
    loaded = store.load(manifest)
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert np.array_equal(loaded.away_runs, snapshot.away_runs)
    assert store.latest(77, model_track="production").snapshot_id == snapshot.snapshot_id
