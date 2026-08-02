from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .market_schema import MarketQuote
from .pricing import OutcomeProbability, PriceEvaluation, evaluate_quote


BEST_AVAILABLE = "BEST_AVAILABLE"


@dataclass(frozen=True)
class MarketCandidate:
    quote: MarketQuote
    probability: OutcomeProbability
    conservative_win_probability: float | None = None
    conflict: bool = False
    fresh: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def _evaluate(candidate: MarketCandidate, minimum_required_roi: float) -> PriceEvaluation:
    return evaluate_quote(
        candidate.quote,
        candidate.probability,
        conservative_win_probability=candidate.conservative_win_probability,
        minimum_required_roi=minimum_required_roi,
        conflict=candidate.conflict,
        fresh=candidate.fresh,
    )


def rank_high_probability(
    candidates: Iterable[MarketCandidate],
    *,
    top_n: int | None = None,
) -> list[MarketCandidate]:
    """Rank outcomes by raw win probability, independent of sportsbook price."""

    # A probability page represents outcomes, not sportsbook quotes. Collapse the
    # same outcome across books and retain the best available display price.
    unique = _best_quote_per_market(list(candidates), allowed_books=None)
    ordered = sorted(
        unique,
        key=lambda candidate: (
            candidate.probability.win,
            -candidate.probability.push,
            candidate.quote.game_pk,
            repr(candidate.quote.market_key),
        ),
        reverse=True,
    )
    return ordered if top_n is None else ordered[: int(top_n)]


def _best_quote_per_market(
    candidates: Iterable[MarketCandidate],
    *,
    allowed_books: set[str] | None,
) -> list[MarketCandidate]:
    selected: dict[tuple, tuple[float, MarketCandidate]] = {}
    normalized_allowed = {book.casefold() for book in allowed_books} if allowed_books else None
    for candidate in candidates:
        if normalized_allowed is not None and candidate.quote.sportsbook.casefold() not in normalized_allowed:
            continue
        decimal = 1.0 + (
            candidate.quote.american_odds / 100.0
            if candidate.quote.american_odds > 0
            else 100.0 / abs(candidate.quote.american_odds)
        )
        current = selected.get(candidate.quote.market_key)
        if current is None or decimal > current[0]:
            selected[candidate.quote.market_key] = (decimal, candidate)
    return [item[1] for item in selected.values()]


def rank_best_value(
    candidates: Iterable[MarketCandidate],
    *,
    sportsbook: str,
    top_n: int = 5,
    minimum_required_roi: float = 0.02,
    allowed_books: set[str] | None = None,
    include_marginal: bool = False,
) -> list[PriceEvaluation]:
    """Rebuild the full value ranking for one globally selected sportsbook."""

    candidate_list = list(candidates)
    if sportsbook.upper() == BEST_AVAILABLE:
        filtered = _best_quote_per_market(candidate_list, allowed_books=allowed_books)
    else:
        target = sportsbook.casefold()
        filtered = [
            candidate
            for candidate in candidate_list
            if candidate.quote.sportsbook.casefold() == target
        ]
    evaluations = [_evaluate(candidate, minimum_required_roi) for candidate in filtered]
    allowed_statuses = {"PLAY", "MARGINAL"} if include_marginal else {"PLAY"}
    evaluations = [item for item in evaluations if item.status in allowed_statuses]
    evaluations.sort(
        key=lambda item: (
            item.expected_roi,
            item.probability_edge,
            item.conservative_probability.win,
            item.quote.game_pk,
        ),
        reverse=True,
    )
    return evaluations[: int(top_n)]
