from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from supermodel.market_store import LocalMarketQuoteStore
from supermodel.odds_provider import (
    OddsHTTPResponse,
    TheOddsAPIClient,
    parse_the_odds_api_quotes,
    refresh_the_odds_api,
)
from supermodel.providers import PregameContext


NOW = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)


def _context(game_pk: int = 123, start: datetime = NOW + timedelta(hours=3)) -> PregameContext:
    return PregameContext(
        game_date="2026-07-30",
        away_team="ATL",
        home_team="MIA",
        game_pk=game_pk,
        game_datetime=start.isoformat().replace("+00:00", "Z"),
        status_abstract="Preview",
        status_detailed="Scheduled",
    )


def _payload(*, spread: float = -1.5, include_book: bool = True):
    bookmakers = []
    if include_book:
        bookmakers = [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "last_update": "2026-07-30T15:59:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Atlanta Braves", "price": -120},
                            {"name": "Miami Marlins", "price": 102},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Atlanta Braves", "price": 135, "point": spread},
                            {"name": "Miami Marlins", "price": -155, "point": -spread},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 8.5},
                            {"name": "Under", "price": -110, "point": 8.5},
                        ],
                    },
                ],
            }
        ]
    return [
        {
            "id": "provider-event",
            "sport_key": "baseball_mlb",
            "commence_time": "2026-07-30T19:00:00Z",
            "away_team": "Atlanta Braves",
            "home_team": "Miami Marlins",
            "bookmakers": bookmakers,
        }
    ]


def test_client_builds_featured_market_request():
    seen = {}

    def transport(url: str, timeout: float) -> OddsHTTPResponse:
        seen["url"] = url
        seen["timeout"] = timeout
        return OddsHTTPResponse(payload=[], headers={})

    client = TheOddsAPIClient("secret", transport=transport)
    client.fetch_mlb_odds(
        slate_date="2026-07-30",
        bookmakers=("draftkings", "fanduel"),
        markets=("h2h", "spreads", "totals"),
    )
    parsed = urlparse(seen["url"])
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/sports/baseball_mlb/odds")
    assert query["bookmakers"] == ["draftkings,fanduel"]
    assert query["markets"] == ["h2h,spreads,totals"]
    assert query["oddsFormat"] == ["american"]


def test_provider_payload_maps_to_game_pk_and_canonical_markets():
    quotes, unmatched, matched = parse_the_odds_api_quotes(
        _payload(),
        contexts=[_context()],
        slate_date="2026-07-30",
        captured_at=NOW,
    )
    assert matched == 1
    assert unmatched == []
    assert len(quotes) == 6
    assert {quote.game_pk for quote in quotes} == {123}
    assert {str(quote.market_type) for quote in quotes} == {
        "moneyline",
        "run_line",
        "game_total",
    }
    assert all(quote.provider == "the_odds_api" for quote in quotes)


def test_current_provider_snapshot_removes_stale_lines(tmp_path):
    responses = iter(
        [
            OddsHTTPResponse(payload=_payload(spread=-1.5), headers={"x-requests-remaining": "99"}),
            OddsHTTPResponse(payload=_payload(spread=-2.5), headers={"x-requests-remaining": "98"}),
            OddsHTTPResponse(payload=_payload(include_book=False), headers={}),
        ]
    )

    def transport(url: str, timeout: float) -> OddsHTTPResponse:
        return next(responses)

    client = TheOddsAPIClient("secret", transport=transport)
    common = dict(
        client=client,
        slate_date="2026-07-30",
        contexts=[_context()],
        market_store_root=tmp_path / "markets",
        raw_snapshot_root=tmp_path / "snapshots",
        bookmakers=("fanduel",),
        captured_at=NOW,
    )
    first = refresh_the_odds_api(**common)
    assert first.quotes_changed == 6
    store = LocalMarketQuoteStore(tmp_path / "markets")
    assert any(quote.line == -1.5 for quote in store.latest("2026-07-30"))

    second = refresh_the_odds_api(**{**common, "captured_at": NOW + timedelta(minutes=5)})
    active = store.latest("2026-07-30")
    assert second.quotes_changed == 4
    assert not any(quote.line == -1.5 for quote in active)
    assert any(quote.line == -2.5 for quote in active)

    refresh_the_odds_api(**{**common, "captured_at": NOW + timedelta(minutes=10)})
    assert store.latest("2026-07-30", sportsbook="FanDuel") == []


def test_provider_does_not_match_same_teams_with_distant_start_time():
    payload = _payload()
    payload[0]["commence_time"] = "2026-07-31T19:00:00Z"
    quotes, unmatched, matched = parse_the_odds_api_quotes(
        payload,
        contexts=[_context()],
        slate_date="2026-07-30",
        captured_at=NOW,
    )
    assert quotes == []
    assert matched == 0
    assert len(unmatched) == 1
