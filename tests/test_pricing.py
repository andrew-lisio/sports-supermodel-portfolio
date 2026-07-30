from datetime import datetime, timezone

import pytest

from supermodel.market_schema import MarketQuote
from supermodel.pricing import OutcomeProbability, evaluate_quote, expected_roi


def _quote(odds: int) -> MarketQuote:
    return MarketQuote(
        game_pk=1,
        sportsbook="DraftKings",
        market_type="moneyline",
        selection="ATL",
        american_odds=odds,
        captured_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )


def test_expected_roi_and_playable_through_for_favorite():
    probability = OutcomeProbability(win=0.58)
    evaluation = evaluate_quote(
        _quote(-120),
        probability,
        minimum_required_roi=0.02,
    )
    assert evaluation.status == "PLAY"
    assert evaluation.expected_roi == pytest.approx(0.0633333333)
    assert evaluation.fair_odds == -138
    assert evaluation.playable_through_odds == -132


def test_push_probability_is_returned_not_lost():
    probability = OutcomeProbability(win=0.50, push=0.10)
    assert expected_roi(probability, -110) == pytest.approx(0.05454545)


def test_conflict_blocks_positive_value():
    evaluation = evaluate_quote(_quote(+120), OutcomeProbability(win=0.50), conflict=True)
    assert evaluation.expected_roi > 0
    assert evaluation.status == "PASS_CONFLICT"
