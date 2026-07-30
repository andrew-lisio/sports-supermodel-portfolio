from datetime import datetime, timedelta, timezone

from supermodel.market_schema import MarketQuote
from supermodel.market_store import LocalMarketQuoteStore


def _quote(*, odds: int, captured_at: datetime) -> MarketQuote:
    return MarketQuote(
        game_pk=123,
        sportsbook="FanDuel",
        market_type="moneyline",
        selection="ATL",
        american_odds=odds,
        captured_at=captured_at,
        event_date="2026-07-30",
    )


def test_market_store_preserves_history_and_returns_latest(tmp_path):
    store = LocalMarketQuoteStore(tmp_path)
    now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    path = store.save_many(
        [
            _quote(odds=-120, captured_at=now),
            _quote(odds=-125, captured_at=now + timedelta(minutes=5)),
        ]
    )
    assert path is not None and path.exists()
    assert len(store.read("2026-07-30")) == 2
    latest = store.latest("2026-07-30")
    assert len(latest) == 1
    assert latest[0].american_odds == -125
    assert store.sportsbooks("2026-07-30") == ["FanDuel"]
