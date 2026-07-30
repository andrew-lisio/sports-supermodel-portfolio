from datetime import datetime, timezone

from supermodel.market_schema import MarketQuote
from supermodel.pricing import OutcomeProbability
from supermodel.rankings import BEST_AVAILABLE, MarketCandidate, rank_best_value, rank_high_probability


NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _candidate(game_pk: int, book: str, team: str, odds: int, probability: float):
    return MarketCandidate(
        quote=MarketQuote(
            game_pk=game_pk,
            sportsbook=book,
            market_type="moneyline",
            selection=team,
            american_odds=odds,
            captured_at=NOW,
        ),
        probability=OutcomeProbability(probability),
    )


def test_high_probability_ignores_prices():
    high = _candidate(1, "FanDuel", "ATL", -300, 0.70)
    value = _candidate(2, "FanDuel", "MIA", +150, 0.50)
    assert rank_high_probability([value, high])[0] is high


def test_global_sportsbook_rebuilds_value_ranking():
    candidates = [
        _candidate(1, "FanDuel", "ATL", -120, 0.58),
        _candidate(1, "DraftKings", "ATL", -140, 0.58),
        _candidate(2, "FanDuel", "MIA", +130, 0.50),
        _candidate(2, "DraftKings", "MIA", +150, 0.50),
    ]
    fanduel = rank_best_value(candidates, sportsbook="FanDuel", minimum_required_roi=0.0)
    draftkings = rank_best_value(candidates, sportsbook="DraftKings", minimum_required_roi=0.0)
    assert fanduel[0].quote.selection == "MIA"
    assert draftkings[0].quote.selection == "MIA"
    assert draftkings[0].expected_roi > fanduel[0].expected_roi


def test_best_available_uses_best_price_for_each_market():
    candidates = [
        _candidate(1, "FanDuel", "ATL", -120, 0.58),
        _candidate(1, "DraftKings", "ATL", -130, 0.58),
    ]
    result = rank_best_value(
        candidates,
        sportsbook=BEST_AVAILABLE,
        minimum_required_roi=0.0,
    )
    assert result[0].quote.sportsbook == "FanDuel"
