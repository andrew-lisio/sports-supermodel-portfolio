from datetime import datetime, timezone

import pytest

from supermodel.market_schema import MarketQuote, MarketType, QuoteSource


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


def test_moneyline_quote_is_canonicalized():
    quote = MarketQuote(
        game_pk=123,
        sportsbook=" FanDuel ",
        market_type="moneyline",
        selection="atl",
        american_odds=-120,
        captured_at=NOW,
        source="manual",
    )
    assert quote.market_type is MarketType.MONEYLINE
    assert quote.source is QuoteSource.MANUAL
    assert quote.sportsbook == "FanDuel"
    assert quote.selection == "ATL"
    assert quote.captured_at == "2026-07-30T12:00:00Z"


def test_team_total_requires_team():
    with pytest.raises(ValueError, match="require a team"):
        MarketQuote(
            game_pk=123,
            sportsbook="Book",
            market_type="team_total",
            selection="OVER",
            line=4.5,
            american_odds=-110,
            captured_at=NOW,
        )
