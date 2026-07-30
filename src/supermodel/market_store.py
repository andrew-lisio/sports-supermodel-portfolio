from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Iterable

from .market_schema import MarketQuote


class LocalMarketQuoteStore:
    """Append-only local store for canonical sportsbook and custom quotes.

    Quotes are partitioned by event date. Reads collapse repeated observations to the
    newest quote for each sportsbook/market outcome, while the raw JSONL remains an
    auditable line-history record.
    """

    def __init__(self, root: str | Path = "runtime/markets") -> None:
        self.root = Path(root)

    def _path(self, event_date: str) -> Path:
        parsed = date.fromisoformat(str(event_date))
        return self.root / f"{parsed.isoformat()}.jsonl"

    def save_many(self, quotes: Iterable[MarketQuote]) -> Path | None:
        quote_list = list(quotes)
        if not quote_list:
            return None
        event_dates = {quote.event_date for quote in quote_list}
        if None in event_dates or len(event_dates) != 1:
            raise ValueError("all stored quotes must share one non-empty event_date")
        event_date = next(iter(event_dates))
        assert event_date is not None
        path = self._path(event_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for quote in quote_list:
                handle.write(json.dumps(quote.to_record(), sort_keys=True) + "\n")
        return path

    def read(self, event_date: str) -> list[MarketQuote]:
        path = self._path(event_date)
        if not path.exists():
            return []
        quotes: list[MarketQuote] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text:
                    quotes.append(MarketQuote.from_record(json.loads(text)))
        return quotes

    def latest(self, event_date: str, *, sportsbook: str | None = None) -> list[MarketQuote]:
        selected: dict[tuple, MarketQuote] = {}
        target = sportsbook.casefold() if sportsbook else None
        for quote in self.read(event_date):
            if target is not None and quote.sportsbook.casefold() != target:
                continue
            current = selected.get(quote.quote_key)
            if current is None or str(quote.captured_at) > str(current.captured_at):
                selected[quote.quote_key] = quote
        return sorted(
            selected.values(),
            key=lambda quote: (
                quote.game_pk,
                quote.sportsbook.casefold(),
                str(quote.market_type),
                quote.selection,
                quote.line if quote.line is not None else -999.0,
                quote.team or "",
            ),
        )

    def sportsbooks(self, event_date: str) -> list[str]:
        return sorted({quote.sportsbook for quote in self.latest(event_date)})
