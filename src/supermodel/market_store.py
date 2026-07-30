from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable

from .market_schema import MarketQuote, QuoteSource


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text or "unknown"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class LocalMarketQuoteStore:
    """Append-only line history plus current provider snapshots.

    Provider snapshots are authoritative for which lines are currently offered. This
    prevents an old spread or total from remaining active after a book moves the number.
    Manual/custom observations continue to use the append-only history directly.
    """

    def __init__(self, root: str | Path = "runtime/markets") -> None:
        self.root = Path(root)

    def _path(self, event_date: str) -> Path:
        parsed = date.fromisoformat(str(event_date))
        return self.root / f"{parsed.isoformat()}.jsonl"

    def _current_root(self, event_date: str) -> Path:
        parsed = date.fromisoformat(str(event_date))
        return self.root / "_current" / parsed.isoformat()

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

    def _current_provider_files(self, event_date: str) -> list[Path]:
        root = self._current_root(event_date)
        return sorted(root.glob("*/*.json")) if root.exists() else []

    def _read_current_file(self, path: Path) -> tuple[str, list[MarketQuote]]:
        document = json.loads(path.read_text(encoding="utf-8"))
        sportsbook = str(document.get("sportsbook") or "")
        quotes = [MarketQuote.from_record(record) for record in document.get("quotes", [])]
        return sportsbook, quotes

    def save_provider_snapshot(
        self,
        quotes: Iterable[MarketQuote],
        *,
        event_date: str,
        provider: str,
        captured_at: datetime,
        expected_sportsbooks: Iterable[str] = (),
        replace_game_pks: Iterable[int] | None = None,
    ) -> int:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        quote_list = list(quotes)
        if any(quote.event_date != event_date for quote in quote_list):
            raise ValueError("provider snapshot quotes must match event_date")
        if any(quote.source is not QuoteSource.PROVIDER for quote in quote_list):
            raise ValueError("provider snapshots may contain provider quotes only")

        by_book: dict[str, list[MarketQuote]] = {}
        for quote in quote_list:
            by_book.setdefault(quote.sportsbook, []).append(quote)
        all_books = set(str(book).strip() for book in expected_sportsbooks if str(book).strip())
        all_books.update(by_book)
        replace_games = (
            {int(game_pk) for game_pk in replace_game_pks}
            if replace_game_pks is not None
            else None
        )

        changed: list[MarketQuote] = []
        active_changes = 0
        current_root = self._current_root(event_date) / _slug(provider)
        for sportsbook in sorted(all_books):
            path = current_root / f"{_slug(sportsbook)}.json"
            previous: dict[tuple, MarketQuote] = {}
            if path.exists():
                _, previous_quotes = self._read_current_file(path)
                previous = {quote.quote_key: quote for quote in previous_quotes}
            incoming = by_book.get(sportsbook, [])
            incoming_by_key = {quote.quote_key: quote for quote in incoming}
            previous_replaced = {
                key: quote
                for key, quote in previous.items()
                if replace_games is None or quote.game_pk in replace_games
            }
            for key in set(previous_replaced) | set(incoming_by_key):
                old = previous_replaced.get(key)
                new = incoming_by_key.get(key)
                if old is None or new is None or old.american_odds != new.american_odds:
                    active_changes += 1
            preserved = (
                [
                    quote
                    for quote in previous.values()
                    if replace_games is not None and quote.game_pk not in replace_games
                ]
                if replace_games is not None
                else []
            )
            active = sorted(
                [*preserved, *incoming],
                key=lambda quote: (
                    quote.game_pk,
                    str(quote.market_type),
                    quote.selection,
                    quote.line if quote.line is not None else -999.0,
                    quote.team or "",
                ),
            )
            for quote in active:
                old = previous.get(quote.quote_key)
                if old is None or old.american_odds != quote.american_odds:
                    changed.append(quote)
            _atomic_json(
                path,
                {
                    "provider": provider,
                    "sportsbook": sportsbook,
                    "event_date": event_date,
                    "captured_at": captured_at.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "quotes": [quote.to_record() for quote in active],
                },
            )
        self.save_many(changed)
        return active_changes

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

    def current_provider_quotes(self, event_date: str) -> tuple[list[MarketQuote], set[str]]:
        quotes: list[MarketQuote] = []
        represented_books: set[str] = set()
        for path in self._current_provider_files(event_date):
            sportsbook, current = self._read_current_file(path)
            if sportsbook:
                represented_books.add(sportsbook.casefold())
            quotes.extend(current)
        return quotes, represented_books

    def latest(self, event_date: str, *, sportsbook: str | None = None) -> list[MarketQuote]:
        current_provider, represented_books = self.current_provider_quotes(event_date)
        candidates = list(current_provider)
        for quote in self.read(event_date):
            # Once a current provider snapshot exists, historical provider observations
            # for that sportsbook cannot reactivate removed lines.
            if quote.source is QuoteSource.PROVIDER and quote.sportsbook.casefold() in represented_books:
                continue
            candidates.append(quote)

        selected: dict[tuple, MarketQuote] = {}
        target = sportsbook.casefold() if sportsbook else None
        for quote in candidates:
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
