from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .market_schema import MarketQuote
from .market_store import LocalMarketQuoteStore
from .pricing import PriceEvaluation, evaluate_quote
from .rankings import MarketCandidate, rank_best_value, rank_high_probability
from .simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot


def _candidate(
    snapshot: SimulationSnapshot,
    quote: MarketQuote,
    *,
    uncertainty_buffer: float,
) -> MarketCandidate:
    probability = snapshot.probability_for_quote(quote)
    conservative = max(0.0, probability.win - float(uncertainty_buffer))
    if conservative + probability.push > 1.0:
        conservative = 1.0 - probability.push
    return MarketCandidate(
        quote=quote,
        probability=probability,
        conservative_win_probability=conservative,
        conflict=bool(snapshot.metadata.get("conflict", False)),
        fresh=bool(snapshot.metadata.get("fresh", True)),
    )


def load_market_candidates(
    *,
    event_date: str,
    model_track: str = "production",
    simulation_store_root: str | Path = "runtime/simulations",
    market_store_root: str | Path = "runtime/markets",
    uncertainty_buffer: float = 0.0,
) -> list[MarketCandidate]:
    snapshot_store = LocalSimulationSnapshotStore(simulation_store_root)
    quote_store = LocalMarketQuoteStore(market_store_root)
    snapshots = {
        snapshot.game_pk: snapshot
        for snapshot in snapshot_store.list_latest(
            event_date=event_date,
            model_track=model_track,
        )
    }
    candidates: list[MarketCandidate] = []
    for quote in quote_store.latest(event_date):
        snapshot = snapshots.get(int(quote.game_pk))
        if snapshot is None:
            continue
        candidates.append(
            _candidate(snapshot, quote, uncertainty_buffer=uncertainty_buffer)
        )
    return candidates


def candidate_record(candidate: MarketCandidate) -> dict[str, Any]:
    quote = candidate.quote
    return {
        **quote.to_record(),
        "win_probability": candidate.probability.win,
        "push_probability": candidate.probability.push,
        "conservative_win_probability": candidate.conservative_win_probability,
        "conflict": candidate.conflict,
        "fresh": candidate.fresh,
    }


def evaluation_record(evaluation: PriceEvaluation) -> dict[str, Any]:
    return {
        **evaluation.quote.to_record(),
        "win_probability": evaluation.probability.win,
        "push_probability": evaluation.probability.push,
        "conservative_win_probability": evaluation.conservative_probability.win,
        "break_even_win_probability": evaluation.break_even_win_probability,
        "probability_edge": evaluation.probability_edge,
        "expected_roi": evaluation.expected_roi,
        "fair_odds": evaluation.fair_odds,
        "playable_through_odds": evaluation.playable_through_odds,
        "status": evaluation.status,
        "conflict": evaluation.conflict,
        "fresh": evaluation.fresh,
    }


def high_probability_records(
    candidates: Iterable[MarketCandidate],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    return [candidate_record(item) for item in rank_high_probability(candidates, top_n=top_n)]


def best_value_records(
    candidates: Iterable[MarketCandidate],
    *,
    sportsbook: str,
    top_n: int = 5,
    minimum_required_roi: float = 0.02,
    allowed_books: set[str] | None = None,
    include_marginal: bool = False,
) -> list[dict[str, Any]]:
    evaluations = rank_best_value(
        candidates,
        sportsbook=sportsbook,
        top_n=top_n,
        minimum_required_roi=minimum_required_roi,
        allowed_books=allowed_books,
        include_marginal=include_marginal,
    )
    return [evaluation_record(item) for item in evaluations]



def high_probability_snapshot_records(
    *,
    event_date: str,
    model_track: str = "production",
    simulation_store_root: str | Path = "runtime/simulations",
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Rank moneyline outcomes directly from saved simulations when no quotes exist."""

    snapshots = LocalSimulationSnapshotStore(simulation_store_root).list_latest(
        event_date=event_date,
        model_track=model_track,
    )
    records: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.away_win_probability is None:
            ties = snapshot.away_runs == snapshot.home_runs
            away_probability = float(
                (snapshot.away_runs > snapshot.home_runs).mean() + 0.5 * ties.mean()
            )
            home_probability = 1.0 - away_probability
        else:
            away_probability = float(snapshot.away_win_probability)
            home_probability = float(snapshot.home_win_probability)
        for selection, probability in (
            (snapshot.away_team, away_probability),
            (snapshot.home_team, home_probability),
        ):
            records.append(
                {
                    "game_pk": snapshot.game_pk,
                    "sportsbook": None,
                    "market_type": "moneyline",
                    "selection": selection,
                    "american_odds": None,
                    "captured_at": snapshot.created_at,
                    "line": None,
                    "team": selection,
                    "provider_updated_at": None,
                    "source": "model",
                    "event_date": event_date,
                    "win_probability": probability,
                    "push_probability": 0.0,
                    "conservative_win_probability": probability,
                    "conflict": bool(snapshot.metadata.get("conflict", False)),
                    "fresh": bool(snapshot.metadata.get("fresh", True)),
                    "odds_available": False,
                }
            )
    records.sort(
        key=lambda item: (item["win_probability"], item["game_pk"], item["selection"]),
        reverse=True,
    )
    return records if top_n is None else records[: int(top_n)]

def evaluate_custom_line(
    *,
    quote: MarketQuote,
    model_track: str = "production",
    simulation_store_root: str | Path = "runtime/simulations",
    uncertainty_buffer: float = 0.0,
    minimum_required_roi: float = 0.02,
) -> PriceEvaluation:
    snapshot = LocalSimulationSnapshotStore(simulation_store_root).latest(
        quote.game_pk,
        model_track=model_track,
    )
    if snapshot is None:
        raise FileNotFoundError(
            f"No {model_track} simulation snapshot exists for game_pk {quote.game_pk}"
        )
    probability = snapshot.probability_for_quote(quote)
    conservative = max(0.0, probability.win - float(uncertainty_buffer))
    if conservative + probability.push > 1.0:
        conservative = 1.0 - probability.push
    return evaluate_quote(
        quote,
        probability,
        conservative_win_probability=conservative,
        minimum_required_roi=minimum_required_roi,
        conflict=bool(snapshot.metadata.get("conflict", False)),
        fresh=bool(snapshot.metadata.get("fresh", True)),
    )
