from datetime import datetime, timezone

import numpy as np

from supermodel.market_schema import MarketQuote
from supermodel.market_store import LocalMarketQuoteStore
from supermodel.platform_views import (
    best_value_records,
    evaluate_custom_line,
    high_probability_records,
    load_market_candidates,
)
from supermodel.rankings import BEST_AVAILABLE
from supermodel.simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def _snapshot(game_pk: int, away: str, home: str, away_p: float) -> SimulationSnapshot:
    return SimulationSnapshot(
        game_pk=game_pk,
        away_team=away,
        home_team=home,
        model_track="production",
        model_version="2.3.3",
        git_commit="abc",
        input_snapshot_hash=f"hash-{game_pk}",
        created_at=NOW,
        random_seed=1,
        away_runs=np.array([5, 3, 4, 2]),
        home_runs=np.array([3, 4, 2, 5]),
        away_win_probability=away_p,
        home_win_probability=1.0 - away_p,
        metadata={"game_date": "2026-07-30", "fresh": True, "conflict": False},
    )


def _quote(game_pk: int, book: str, selection: str, odds: int) -> MarketQuote:
    return MarketQuote(
        game_pk=game_pk,
        sportsbook=book,
        market_type="moneyline",
        selection=selection,
        american_odds=odds,
        captured_at=NOW,
        event_date="2026-07-30",
    )


def test_page_services_load_snapshots_and_rebuild_rankings(tmp_path):
    sim_root = tmp_path / "simulations"
    market_root = tmp_path / "markets"
    sim_store = LocalSimulationSnapshotStore(sim_root)
    sim_store.save(_snapshot(1, "ATL", "MIA", 0.60))
    sim_store.save(_snapshot(2, "BOS", "NYY", 0.52))
    LocalMarketQuoteStore(market_root).save_many(
        [
            _quote(1, "FanDuel", "ATL", -120),
            _quote(1, "DraftKings", "ATL", -135),
            _quote(2, "FanDuel", "BOS", +120),
            _quote(2, "DraftKings", "BOS", +140),
        ]
    )
    candidates = load_market_candidates(
        event_date="2026-07-30",
        simulation_store_root=sim_root,
        market_store_root=market_root,
    )
    high = high_probability_records(candidates, top_n=2)
    assert high[0]["selection"] == "ATL"
    value = best_value_records(
        candidates,
        sportsbook=BEST_AVAILABLE,
        minimum_required_roi=0.0,
        allowed_books={"FanDuel", "DraftKings"},
    )
    assert value[0]["selection"] == "BOS"
    assert value[0]["sportsbook"] == "DraftKings"


def test_custom_line_checker_prices_from_latest_snapshot(tmp_path):
    sim_root = tmp_path / "simulations"
    LocalSimulationSnapshotStore(sim_root).save(_snapshot(1, "ATL", "MIA", 0.60))
    evaluation = evaluate_custom_line(
        quote=_quote(1, "Custom", "ATL", -110),
        simulation_store_root=sim_root,
        minimum_required_roi=0.0,
    )
    assert evaluation.probability.win == 0.60
    assert evaluation.expected_roi > 0.0
