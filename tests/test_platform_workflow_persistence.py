from datetime import datetime, timezone

import numpy as np
import pandas as pd

from supermodel.market_store import LocalMarketQuoteStore
from supermodel.odds_input import ManualMoneyline
from supermodel.providers import PregameContext
from supermodel.simulation_store import LocalSimulationSnapshotStore
from supermodel.workflow import CapturedSlate, _persist_platform_outputs


def test_workflow_persists_quotes_and_both_model_tracks(tmp_path):
    schedule = tmp_path / "schedule.json"
    schedule.write_text("{}", encoding="utf-8")
    market_snapshot = tmp_path / "market.json"
    market_snapshot.write_text("{}", encoding="utf-8")
    captured = CapturedSlate(
        game_date="2026-07-30",
        captured_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        schedule_path=schedule,
        pregame_paths=(),
        starter_paths=(),
        advanced_paths=(),
        contexts=(
            PregameContext(
                game_date="2026-07-30",
                away_team="ATL",
                home_team="MIA",
                game_pk=123,
                game_datetime="2026-07-30T23:00:00Z",
            ),
        ),
    )
    evaluation = pd.DataFrame(
        [
            {
                "game_pk": 123,
                "away_team": "ATL",
                "home_team": "MIA",
                "away_probability": 0.60,
                "home_probability": 0.40,
                "shadow_away_probability": 0.58,
                "shadow_home_probability": 0.42,
                "selection_status": "PLAY",
                "shadow_selection_status": "PLAY",
                "history_freshness_status": "PASS",
                "history_checked_through": "2026-07-29",
                "lineups_confirmed": True,
            }
        ]
    )
    quote_path, manifests = _persist_platform_outputs(
        captured_slate=captured,
        evaluation=evaluation,
        moneylines=[ManualMoneyline("2026-07-30", "ATL", "MIA", -120, +110, 123)],
        market_timestamp=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        market_snapshot_path=market_snapshot,
        production_draws={123: (np.array([5, 4]), np.array([3, 6]))},
        shadow_draws={123: (np.array([4, 2]), np.array([3, 5]))},
        sportsbook_name="Custom",
        market_store_root=tmp_path / "markets",
        simulation_store_root=tmp_path / "simulations",
    )
    assert quote_path is not None and quote_path.exists()
    assert len(manifests) == 2
    assert len(LocalMarketQuoteStore(tmp_path / "markets").latest("2026-07-30")) == 2
    store = LocalSimulationSnapshotStore(tmp_path / "simulations")
    assert store.latest(123, model_track="production").away_win_probability == 0.60
    assert store.latest(123, model_track="shadow").away_win_probability == 0.58
