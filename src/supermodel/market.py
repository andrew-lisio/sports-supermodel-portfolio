from __future__ import annotations

import math
from typing import Iterable


def american_to_decimal(odds: int) -> float:
    """Convert non-zero American odds to decimal odds."""
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def american_implied_probability(odds: int) -> float:
    """Return the raw implied probability for American odds."""
    return 1.0 / american_to_decimal(odds)


def no_vig_probabilities(away_odds: int, home_odds: int) -> tuple[float, float]:
    """Normalize a two-way moneyline so the two probabilities sum to one."""
    away_raw = american_implied_probability(away_odds)
    home_raw = american_implied_probability(home_odds)
    total = away_raw + home_raw
    if total <= 0:
        raise ValueError("invalid two-way market")
    return away_raw / total, home_raw / total


def probability_to_american(probability: float) -> int:
    """Convert a probability strictly between zero and one to American odds."""
    if not 0 < probability < 1:
        raise ValueError("Probability must be strictly between 0 and 1")
    if probability >= 0.5:
        return int(round(-100.0 * probability / (1.0 - probability)))
    return int(round(100.0 * (1.0 - probability) / probability))


def combine_american_odds(odds: Iterable[int]) -> int:
    """Combine independent parlay legs expressed as American odds."""
    decimal = math.prod(american_to_decimal(int(value)) for value in odds)
    if decimal <= 1:
        raise ValueError("combined decimal odds must exceed 1")
    profit = decimal - 1.0
    return int(round(profit * 100)) if profit >= 1.0 else int(round(-100.0 / profit))
