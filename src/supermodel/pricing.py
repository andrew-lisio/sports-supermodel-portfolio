from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from .market import american_implied_probability, american_to_decimal
from .market_schema import MarketQuote
from .odds_input import decimal_to_american


@dataclass(frozen=True)
class OutcomeProbability:
    win: float
    push: float = 0.0

    def __post_init__(self) -> None:
        win = float(self.win)
        push = float(self.push)
        if not math.isfinite(win) or not math.isfinite(push):
            raise ValueError("probabilities must be finite")
        if win < 0.0 or push < 0.0 or win + push > 1.0 + 1e-12:
            raise ValueError("win and push probabilities must be non-negative and sum to <= 1")
        object.__setattr__(self, "win", win)
        object.__setattr__(self, "push", push)

    @property
    def loss(self) -> float:
        return max(0.0, 1.0 - self.win - self.push)


@dataclass(frozen=True)
class PriceEvaluation:
    quote: MarketQuote
    probability: OutcomeProbability
    conservative_probability: OutcomeProbability
    break_even_win_probability: float
    probability_edge: float
    expected_roi: float
    fair_odds: int
    playable_through_odds: int
    minimum_required_roi: float
    status: str
    conflict: bool
    fresh: bool

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quote"] = self.quote.to_record()
        payload["probability"] = asdict(self.probability)
        payload["conservative_probability"] = asdict(self.conservative_probability)
        return payload


def expected_roi(probability: OutcomeProbability, american_odds: int) -> float:
    decimal = american_to_decimal(int(american_odds))
    return probability.win * (decimal - 1.0) - probability.loss


def break_even_win_probability(american_odds: int, *, push_probability: float = 0.0) -> float:
    decimal = american_to_decimal(int(american_odds))
    return (1.0 - float(push_probability)) / decimal


def fair_decimal_odds(probability: OutcomeProbability) -> float:
    if probability.win <= 0.0:
        raise ValueError("fair odds are undefined when win probability is zero")
    return (1.0 - probability.push) / probability.win


def fair_american_odds(probability: OutcomeProbability) -> int:
    decimal = fair_decimal_odds(probability)
    if decimal <= 1.0:
        return -100000
    return decimal_to_american(decimal)


def playable_through_odds(
    probability: OutcomeProbability,
    *,
    minimum_required_roi: float = 0.02,
) -> int:
    required_roi = float(minimum_required_roi)
    if required_roi < 0.0:
        raise ValueError("minimum_required_roi cannot be negative")
    if probability.win <= 0.0:
        raise ValueError("playable-through odds are undefined when win probability is zero")
    decimal = (1.0 + required_roi - probability.push) / probability.win
    if decimal <= 1.0:
        return -100000
    return decimal_to_american(decimal)


def evaluate_quote(
    quote: MarketQuote,
    probability: OutcomeProbability,
    *,
    conservative_win_probability: float | None = None,
    minimum_required_roi: float = 0.02,
    conflict: bool = False,
    fresh: bool = True,
) -> PriceEvaluation:
    conservative_win = (
        probability.win
        if conservative_win_probability is None
        else float(conservative_win_probability)
    )
    conservative = OutcomeProbability(win=conservative_win, push=probability.push)
    break_even = break_even_win_probability(
        quote.american_odds, push_probability=probability.push
    )
    roi = expected_roi(conservative, quote.american_odds)
    if not fresh:
        status = "PASS_STALE"
    elif conflict:
        status = "PASS_CONFLICT"
    elif roi >= minimum_required_roi:
        status = "PLAY"
    elif roi > 0.0:
        status = "MARGINAL"
    else:
        status = "NO_EDGE"
    return PriceEvaluation(
        quote=quote,
        probability=probability,
        conservative_probability=conservative,
        break_even_win_probability=break_even,
        probability_edge=conservative.win - break_even,
        expected_roi=roi,
        fair_odds=fair_american_odds(conservative),
        playable_through_odds=playable_through_odds(
            conservative, minimum_required_roi=minimum_required_roi
        ),
        minimum_required_roi=float(minimum_required_roi),
        status=status,
        conflict=bool(conflict),
        fresh=bool(fresh),
    )


def normalized_two_way_probabilities(first_odds: int, second_odds: int) -> tuple[float, float]:
    first = american_implied_probability(first_odds)
    second = american_implied_probability(second_odds)
    total = first + second
    if total <= 0.0:
        raise ValueError("invalid two-way prices")
    return first / total, second / total
