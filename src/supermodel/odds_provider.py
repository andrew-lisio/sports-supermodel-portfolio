from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .market_schema import MarketQuote, MarketType, QuoteSource
from .storage import (
    ObjectBackend,
    StorageBackend,
    StorageSettings,
    create_market_quote_store,
    create_object_store,
)
from .providers import PregameContext


THE_ODDS_API_PROVIDER = "the_odds_api"
THE_ODDS_API_SPORT = "baseball_mlb"
DEFAULT_BOOKMAKERS = ("draftkings", "fanduel", "hardrockbet")
DEFAULT_MARKETS = ("h2h", "spreads", "totals")

BOOKMAKER_TITLES: dict[str, str] = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "hardrockbet": "Hard Rock Bet",
    "hardrockbet_az": "Hard Rock Bet (AZ)",
    "hardrockbet_fl": "Hard Rock Bet (FL)",
    "hardrockbet_oh": "Hard Rock Bet (OH)",
    "betmgm": "BetMGM",
    "betrivers": "BetRivers",
    "williamhill_us": "Caesars",
    "fanatics": "Fanatics",
}

_TEAM_ALIASES: dict[str, str] = {
    "arizona diamondbacks": "AZ",
    "atlanta braves": "ATL",
    "baltimore orioles": "BAL",
    "boston red sox": "BOS",
    "chicago cubs": "CHC",
    "chicago white sox": "CWS",
    "cincinnati reds": "CIN",
    "cleveland guardians": "CLE",
    "colorado rockies": "COL",
    "detroit tigers": "DET",
    "houston astros": "HOU",
    "kansas city royals": "KC",
    "los angeles angels": "LAA",
    "la angels": "LAA",
    "los angeles dodgers": "LAD",
    "la dodgers": "LAD",
    "miami marlins": "MIA",
    "milwaukee brewers": "MIL",
    "minnesota twins": "MIN",
    "new york mets": "NYM",
    "ny mets": "NYM",
    "new york yankees": "NYY",
    "ny yankees": "NYY",
    "oakland athletics": "ATH",
    "sacramento athletics": "ATH",
    "athletics": "ATH",
    "as": "ATH",
    "philadelphia phillies": "PHI",
    "pittsburgh pirates": "PIT",
    "san diego padres": "SD",
    "san francisco giants": "SF",
    "seattle mariners": "SEA",
    "st louis cardinals": "STL",
    "saint louis cardinals": "STL",
    "tampa bay rays": "TB",
    "texas rangers": "TEX",
    "toronto blue jays": "TOR",
    "washington nationals": "WSH",
}
_TEAM_ABBREVIATIONS = frozenset(_TEAM_ALIASES.values())


class OddsProviderError(RuntimeError):
    pass


def _utc_iso(value: datetime | str) -> str:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_name(value: str) -> str:
    text = value.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def team_abbreviation(value: str) -> str | None:
    normalized = _normalize_name(value)
    if normalized in _TEAM_ALIASES:
        return _TEAM_ALIASES[normalized]
    upper = str(value).strip().upper()
    if upper in _TEAM_ABBREVIATIONS:
        return upper
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class OddsHTTPResponse:
    payload: list[dict[str, Any]]
    headers: dict[str, str]


Transport = Callable[[str, float], OddsHTTPResponse]


def _default_transport(url: str, timeout: float) -> OddsHTTPResponse:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "sports-supermodel/2.4"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed provider host
            raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    except HTTPError as exc:  # pragma: no cover - exercised through injected transports
        raise OddsProviderError(f"The Odds API request failed with HTTP {exc.code}") from exc
    except URLError as exc:  # pragma: no cover - exercised through injected transports
        raise OddsProviderError(f"The Odds API connection failed: {exc.reason}") from exc
    except Exception as exc:  # pragma: no cover - exercised through injected transports
        raise OddsProviderError(
            f"The Odds API request failed with {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, list):
        raise OddsProviderError("The Odds API returned a non-list odds payload")
    return OddsHTTPResponse(payload=payload, headers=headers)


class TheOddsAPIClient:
    """Small licensed-provider client for The Odds API v4 featured MLB markets."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.the-odds-api.com/v4",
        timeout: float = 30.0,
        transport: Transport | None = None,
    ) -> None:
        if not str(api_key).strip():
            raise ValueError("The Odds API key is required")
        self.api_key = str(api_key).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.transport = transport or _default_transport

    def fetch_mlb_odds(
        self,
        *,
        slate_date: str,
        bookmakers: Sequence[str] = DEFAULT_BOOKMAKERS,
        markets: Sequence[str] = DEFAULT_MARKETS,
    ) -> OddsHTTPResponse:
        target = date.fromisoformat(slate_date)
        # Covers the complete US slate while avoiding unrelated following-day games.
        start = datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=4)
        end = start + timedelta(hours=28)
        params = {
            "apiKey": self.api_key,
            "bookmakers": ",".join(dict.fromkeys(str(item).strip() for item in bookmakers if str(item).strip())),
            "markets": ",".join(dict.fromkeys(str(item).strip() for item in markets if str(item).strip())),
            "oddsFormat": "american",
            "dateFormat": "iso",
            "commenceTimeFrom": _utc_iso(start),
            "commenceTimeTo": _utc_iso(end),
        }
        if not params["bookmakers"]:
            raise ValueError("at least one bookmaker key is required")
        if not params["markets"]:
            raise ValueError("at least one market key is required")
        url = f"{self.base_url}/sports/{THE_ODDS_API_SPORT}/odds?{urlencode(params)}"
        return self.transport(url, self.timeout)


@dataclass(frozen=True)
class OddsRefreshReport:
    status: str
    provider: str
    slate_date: str
    captured_at_utc: str
    events_received: int
    events_matched: int
    unmatched_events: tuple[dict[str, Any], ...]
    quotes_received: int
    quotes_changed: int
    sportsbooks: tuple[str, ...]
    raw_snapshot_path: str
    quota_remaining: int | None
    quota_used: int | None
    quota_last: int | None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["unmatched_events"] = list(payload["unmatched_events"])
        payload["sportsbooks"] = list(payload["sportsbooks"])
        return payload


def _nearest_context(
    event: Mapping[str, Any], contexts: Sequence[PregameContext]
) -> PregameContext | None:
    away = team_abbreviation(str(event.get("away_team", "")))
    home = team_abbreviation(str(event.get("home_team", "")))
    if not away or not home:
        return None
    candidates = [
        context
        for context in contexts
        if context.game_pk is not None
        and team_abbreviation(context.away_team) == away
        and team_abbreviation(context.home_team) == home
    ]
    if not candidates:
        return None
    event_time = _parse_datetime(str(event.get("commence_time") or ""))
    if len(candidates) == 1:
        context_time = _parse_datetime(candidates[0].game_datetime)
        if event_time is not None and context_time is not None:
            if abs((context_time - event_time).total_seconds()) > 8 * 3600:
                return None
        return candidates[0]
    if event_time is None:
        return None
    scored: list[tuple[float, PregameContext]] = []
    for context in candidates:
        context_time = _parse_datetime(context.game_datetime)
        if context_time is not None:
            scored.append((abs((context_time - event_time).total_seconds()), context))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    if scored[0][0] > 8 * 3600:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _american_price(value: Any) -> int | None:
    try:
        price = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return price if price != 0 and abs(price) >= 100 else None


def _provider_updated(market: Mapping[str, Any], bookmaker: Mapping[str, Any], fallback: datetime) -> str:
    value = market.get("last_update") or bookmaker.get("last_update")
    parsed = _parse_datetime(str(value)) if value else None
    return _utc_iso(parsed or fallback)


def parse_the_odds_api_quotes(
    payload: Sequence[Mapping[str, Any]],
    *,
    contexts: Sequence[PregameContext],
    slate_date: str,
    captured_at: datetime,
) -> tuple[list[MarketQuote], list[dict[str, Any]], int]:
    quotes: list[MarketQuote] = []
    unmatched: list[dict[str, Any]] = []
    matched_events = 0
    for event in payload:
        context = _nearest_context(event, contexts)
        if context is None:
            unmatched.append(
                {
                    "provider_event_id": event.get("id"),
                    "away_team": event.get("away_team"),
                    "home_team": event.get("home_team"),
                    "commence_time": event.get("commence_time"),
                }
            )
            continue
        matched_events += 1
        game_pk = int(context.game_pk)
        context_away = team_abbreviation(context.away_team)
        context_home = team_abbreviation(context.home_team)
        for bookmaker in event.get("bookmakers", []) or []:
            if not isinstance(bookmaker, Mapping):
                continue
            book_key = str(bookmaker.get("key") or "").strip()
            book_title = str(bookmaker.get("title") or BOOKMAKER_TITLES.get(book_key) or book_key).strip()
            if not book_title:
                continue
            for market in bookmaker.get("markets", []) or []:
                if not isinstance(market, Mapping):
                    continue
                market_key = str(market.get("key") or "")
                updated = _provider_updated(market, bookmaker, captured_at)
                for outcome in market.get("outcomes", []) or []:
                    if not isinstance(outcome, Mapping):
                        continue
                    price = _american_price(outcome.get("price"))
                    if price is None:
                        continue
                    name = str(outcome.get("name") or "")
                    common = {
                        "game_pk": game_pk,
                        "sportsbook": book_title,
                        "american_odds": price,
                        "captured_at": captured_at,
                        "provider_updated_at": updated,
                        "source": QuoteSource.PROVIDER,
                        "event_date": slate_date,
                        "provider": THE_ODDS_API_PROVIDER,
                        "provider_event_id": str(event.get("id") or "") or None,
                        "provider_bookmaker_key": book_key or None,
                        "provider_market_key": market_key or None,
                    }
                    if market_key == "h2h":
                        selection = team_abbreviation(name)
                        if selection in {context_away, context_home}:
                            quotes.append(
                                MarketQuote(
                                    market_type=MarketType.MONEYLINE,
                                    selection=selection,
                                    **common,
                                )
                            )
                    elif market_key == "spreads":
                        selection = team_abbreviation(name)
                        try:
                            point = float(outcome.get("point"))
                        except (TypeError, ValueError):
                            continue
                        if selection in {context_away, context_home}:
                            quotes.append(
                                MarketQuote(
                                    market_type=MarketType.RUN_LINE,
                                    selection=selection,
                                    line=point,
                                    **common,
                                )
                            )
                    elif market_key == "totals":
                        selection = name.strip().upper()
                        try:
                            point = float(outcome.get("point"))
                        except (TypeError, ValueError):
                            continue
                        if selection in {"OVER", "UNDER"}:
                            quotes.append(
                                MarketQuote(
                                    market_type=MarketType.GAME_TOTAL,
                                    selection=selection,
                                    line=point,
                                    **common,
                                )
                            )
    deduplicated: dict[tuple, MarketQuote] = {}
    for quote in quotes:
        existing = deduplicated.get(quote.quote_key)
        if existing is None or str(quote.provider_updated_at or quote.captured_at) > str(
            existing.provider_updated_at or existing.captured_at
        ):
            deduplicated[quote.quote_key] = quote
    return list(deduplicated.values()), unmatched, matched_events


def _write_raw_snapshot(
    root: str | Path,
    *,
    slate_date: str,
    captured_at: datetime,
    payload: Sequence[Mapping[str, Any]],
    headers: Mapping[str, str],
) -> Path:
    path = (
        Path(root)
        / slate_date
        / f"{captured_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "provider": THE_ODDS_API_PROVIDER,
        "captured_at": _utc_iso(captured_at),
        "headers": {
            key: value
            for key, value in headers.items()
            if key in {"x-requests-remaining", "x-requests-used", "x-requests-last"}
        },
        "payload": list(payload),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _header_int(headers: Mapping[str, str], key: str) -> int | None:
    try:
        return int(headers.get(key, ""))
    except (TypeError, ValueError):
        return None


def refresh_the_odds_api(
    *,
    client: TheOddsAPIClient,
    slate_date: str,
    contexts: Sequence[PregameContext],
    market_store_root: str | Path = "runtime/markets",
    raw_snapshot_root: str | Path = "runtime/snapshots/odds/the_odds_api",
    bookmakers: Sequence[str] = DEFAULT_BOOKMAKERS,
    markets: Sequence[str] = DEFAULT_MARKETS,
    captured_at: datetime | None = None,
) -> OddsRefreshReport:
    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    response = client.fetch_mlb_odds(
        slate_date=slate_date,
        bookmakers=bookmakers,
        markets=markets,
    )
    snapshot_path = _write_raw_snapshot(
        raw_snapshot_root,
        slate_date=slate_date,
        captured_at=timestamp,
        payload=response.payload,
        headers=response.headers,
    )
    snapshot_reference = str(snapshot_path)
    storage_settings = StorageSettings.from_env()
    if (
        storage_settings.backend is StorageBackend.POSTGRES
        or storage_settings.object_backend is ObjectBackend.S3
    ):
        object_store = create_object_store(storage_settings)
        snapshot_reference = object_store.put_bytes(
            f"raw/odds/the_odds_api/{slate_date}/{snapshot_path.name}",
            snapshot_path.read_bytes(),
            content_type="application/json",
        )
    quotes, unmatched, matched_events = parse_the_odds_api_quotes(
        response.payload,
        contexts=contexts,
        slate_date=slate_date,
        captured_at=timestamp,
    )
    expected_titles = [BOOKMAKER_TITLES.get(key, key) for key in bookmakers]
    store = create_market_quote_store(market_store_root)
    written = store.save_provider_snapshot(
        quotes,
        event_date=slate_date,
        provider=THE_ODDS_API_PROVIDER,
        captured_at=timestamp,
        expected_sportsbooks=expected_titles,
        replace_game_pks=(int(context.game_pk) for context in contexts if context.game_pk is not None),
    )
    books = tuple(sorted({quote.sportsbook for quote in quotes}))
    return OddsRefreshReport(
        status="PASS",
        provider=THE_ODDS_API_PROVIDER,
        slate_date=slate_date,
        captured_at_utc=_utc_iso(timestamp),
        events_received=len(response.payload),
        events_matched=matched_events,
        unmatched_events=tuple(unmatched),
        quotes_received=len(quotes),
        quotes_changed=written,
        sportsbooks=books,
        raw_snapshot_path=snapshot_reference,
        quota_remaining=_header_int(response.headers, "x-requests-remaining"),
        quota_used=_header_int(response.headers, "x-requests-used"),
        quota_last=_header_int(response.headers, "x-requests-last"),
    )
