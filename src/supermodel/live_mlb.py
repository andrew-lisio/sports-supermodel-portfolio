from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Any, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ._version import __version__
from .advanced_features import (
    advanced_snapshot_payload,
    aggregate_lineup_stats,
    derive_travel_load,
    derive_weather_features,
    parse_recent_bullpen_usage,
    parse_team_fielding_stats,
    parse_team_pitching_stats,
    parse_venue_location,
)
from .game_registry import ImmutableSnapshotStore, parse_mlb_schedule
from .mlb_v2 import (
    PoissonScoreModel,
    RANDOM_SEED,
    V2Ensemble,
)
from .mlb_v2 import simulate_poisson_score_distribution
from .providers import PregameContext
from .selection_policy import SelectionPolicy, apply_selection_policy
from .starter_features import (
    build_starter_snapshot_payload,
    parse_pitcher_season_stats as parse_point_in_time_pitcher_stats,
)
from .odds_input import ManualMoneyline, load_moneylines
from .market import (
    american_implied_probability,
    american_to_decimal,
    combine_american_odds,
    no_vig_probabilities,
    probability_to_american,
)

@dataclass(frozen=True)
class LiveEvaluationConfig:
    """Configuration for prediction, simulation, and confidence ranking.

    V2.3.3 intentionally contains no bankroll management, stake sizing, or Kelly
    criterion. Market prices are used only to report implied probability, fair odds,
    and model-versus-market edges.
    """

    simulations: int = 100_000
    score_simulation_weight: float = 0.20
    home_field_logit_adjustment: float = 0.0
    top_n: int = 5
    selection_policy: SelectionPolicy = field(default_factory=SelectionPolicy)

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise ValueError("simulations must be positive")
        if not 0.0 <= self.score_simulation_weight <= 1.0:
            raise ValueError("score_simulation_weight must be between 0 and 1")
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")


class MLBStatsHTTPClient:
    """Minimal no-key client for public MLB Stats API endpoints.

    Network responses should be written to ``ImmutableSnapshotStore`` before they are
    used in a real evaluation. Tests use frozen payloads and never require a network.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://statsapi.mlb.com/api",
        timeout_seconds: float = 20.0,
        retries: int = 2,
        user_agent: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.user_agent = user_agent or f"SportsSuperModel/{__version__} (+recreational research use)"

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.load(response)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"MLB Stats API request failed for {url}: {last_error}") from last_error

    def schedule(self, game_date: str) -> dict[str, Any]:
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "date": game_date,
                "hydrate": "probablePitcher,team,venue",
            },
        )

    def schedule_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "startDate": start_date,
                "endDate": end_date,
                "hydrate": "team,venue",
            },
        )

    def completed_schedule_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "startDate": start_date,
                "endDate": end_date,
                "hydrate": "team,venue,linescore,probablePitcher",
            },
        )

    def live_feed(self, game_pk: int) -> dict[str, Any]:
        return self._get_json(f"v1.1/game/{int(game_pk)}/feed/live")

    def boxscore(self, game_pk: int) -> dict[str, Any]:
        return self._get_json(f"v1/game/{int(game_pk)}/boxscore")

    def person_pitching_stats(self, person_id: int, season: int) -> dict[str, Any]:
        return self._get_json(
            f"v1/people/{int(person_id)}/stats",
            {"stats": "season", "group": "pitching", "season": int(season)},
        )

    def person_hitting_stats(self, person_id: int, season: int) -> dict[str, Any]:
        return self._get_json(
            f"v1/people/{int(person_id)}/stats",
            {"stats": "season", "group": "hitting", "season": int(season)},
        )

    def people_hitting_stats(self, person_ids: list[int], season: int) -> dict[str, Any]:
        ids = sorted({int(value) for value in person_ids if int(value) > 0})
        if not ids:
            return {"people": []}
        return self._get_json(
            "v1/people",
            {
                "personIds": ",".join(str(value) for value in ids),
                "hydrate": f"stats(group=[hitting],type=[season],season={int(season)})",
            },
        )

    def team_stats(self, team_id: int, season: int, group: str) -> dict[str, Any]:
        if group not in {"pitching", "fielding", "hitting"}:
            raise ValueError("group must be pitching, fielding, or hitting")
        return self._get_json(
            f"v1/teams/{int(team_id)}/stats",
            {"stats": "season", "group": group, "season": int(season)},
        )

    def venue(self, venue_id: int) -> dict[str, Any]:
        return self._get_json(f"v1/venues/{int(venue_id)}")

    def recent_team_schedule(self, team_id: int, end_date: str, days: int = 4) -> dict[str, Any]:
        end = datetime.fromisoformat(end_date).date()
        start = end - timedelta(days=days)
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "teamId": int(team_id),
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "hydrate": "linescore,venue",
            },
        )


def _first_stat_split(payload: dict[str, Any]) -> dict[str, Any]:
    for block in payload.get("stats", []):
        splits = block.get("splits") or []
        if splits:
            stat = splits[0].get("stat")
            if isinstance(stat, dict):
                return stat
    return {}


def _float_stat(stat: dict[str, Any], key: str) -> float | None:
    value = stat.get(key)
    if value in (None, "", "-.--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_pitcher_season_stats(payload: dict[str, Any]) -> dict[str, float | None]:
    """Backward-compatible public parser for point-in-time season statistics."""

    return parse_point_in_time_pitcher_stats(payload)


def _team_boxscore(feed: dict[str, Any], side: str) -> dict[str, Any]:
    return (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}).get(side) or {}


def _player_name(feed: dict[str, Any], person_id: int) -> str | None:
    players = ((feed.get("gameData") or {}).get("players") or {})
    player = players.get(f"ID{int(person_id)}") or players.get(str(int(person_id))) or {}
    return player.get("fullName")


def enrich_context_from_live_feed(context: PregameContext, feed: dict[str, Any]) -> PregameContext:
    game_data = feed.get("gameData") or {}
    status = game_data.get("status") or {}
    context.status_abstract = status.get("abstractGameState") or context.status_abstract
    context.status_detailed = status.get("detailedState") or context.status_detailed

    probable = game_data.get("probablePitchers") or {}
    away_pitcher = probable.get("away") or {}
    home_pitcher = probable.get("home") or {}
    if away_pitcher.get("id") is not None:
        context.away_probable_pitcher_id = int(away_pitcher["id"])
        context.away_probable_pitcher_name = away_pitcher.get("fullName")
    if home_pitcher.get("id") is not None:
        context.home_probable_pitcher_id = int(home_pitcher["id"])
        context.home_probable_pitcher_name = home_pitcher.get("fullName")
    context.probable_pitchers_confirmed = bool(
        context.away_probable_pitcher_id and context.home_probable_pitcher_id
    )

    away_order = _team_boxscore(feed, "away").get("battingOrder") or []
    home_order = _team_boxscore(feed, "home").get("battingOrder") or []
    context.away_lineup_ids = [int(pid) for pid in away_order]
    context.home_lineup_ids = [int(pid) for pid in home_order]
    context.away_lineup_names = [
        name for pid in context.away_lineup_ids if (name := _player_name(feed, pid))
    ]
    context.home_lineup_names = [
        name for pid in context.home_lineup_ids if (name := _player_name(feed, pid))
    ]
    context.lineups_confirmed = len(away_order) >= 9 and len(home_order) >= 9

    weather = game_data.get("weather") or {}
    context.temperature_f = _float_stat(weather, "temp")
    context.weather_condition = weather.get("condition")
    context.wind_description = weather.get("wind")
    context.roof_status = (game_data.get("venue") or {}).get("roofType") or context.roof_status
    return context


def apply_pitcher_stats_to_context(
    context: PregameContext,
    *,
    away_payload: dict[str, Any] | None,
    home_payload: dict[str, Any] | None,
) -> PregameContext:
    away = parse_pitcher_season_stats(away_payload or {})
    home = parse_pitcher_season_stats(home_payload or {})
    context.away_starter_fip = away["starter_fip"]
    context.home_starter_fip = home["starter_fip"]
    context.away_k_minus_bb = away["starter_k_minus_bb"]
    context.home_k_minus_bb = home["starter_k_minus_bb"]
    context.away_starter_era = away["season_era"]
    context.home_starter_era = home["season_era"]
    context.away_starter_whip = away["season_whip"]
    context.home_starter_whip = home["season_whip"]
    context.away_starter_innings = away["season_innings"]
    context.home_starter_innings = home["season_innings"]
    context.away_starter_games_started = away["games_started"]
    context.home_starter_games_started = home["games_started"]
    context.away_starter_k_rate = away["starter_k_rate"]
    context.home_starter_k_rate = home["starter_k_rate"]
    context.away_starter_bb_rate = away["starter_bb_rate"]
    context.home_starter_bb_rate = home["starter_bb_rate"]
    context.away_starter_k_per_9 = away["starter_k_per_9"]
    context.home_starter_k_per_9 = home["starter_k_per_9"]
    context.away_starter_bb_per_9 = away["starter_bb_per_9"]
    context.home_starter_bb_per_9 = home["starter_bb_per_9"]
    context.away_starter_hr_per_9 = away["starter_hr_per_9"]
    context.home_starter_hr_per_9 = home["starter_hr_per_9"]
    context.away_starter_hits_per_9 = away["starter_hits_per_9"]
    context.home_starter_hits_per_9 = home["starter_hits_per_9"]
    context.away_starter_ground_to_air = away["starter_ground_to_air"]
    context.home_starter_ground_to_air = home["starter_ground_to_air"]
    return context


def _optional_client_call(client: Any, method_name: str, *args: Any) -> dict[str, Any] | None:
    method = getattr(client, method_name, None)
    if method is None:
        return None
    try:
        payload = method(*args)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _people_hitting_payloads(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not payload:
        return {}
    output: dict[int, dict[str, Any]] = {}
    for person in payload.get("people", []) or []:
        person_id = person.get("id")
        stats = person.get("stats")
        if person_id is None or not isinstance(stats, list):
            continue
        output[int(person_id)] = {"stats": stats}
    return output


def _recent_completed_games(
    schedule_payload: dict[str, Any] | None,
    *,
    target_date: str,
    exclude_game_pk: int,
) -> list[tuple[int, dict[str, Any]]]:
    if not schedule_payload:
        return []
    target = datetime.fromisoformat(target_date).date()
    rows: list[tuple[int, dict[str, Any]]] = []
    for date_block in schedule_payload.get("dates", []):
        block_date = datetime.fromisoformat(str(date_block.get("date"))).date()
        days_ago = max(0, (target - block_date).days - 1)
        for game in date_block.get("games", []):
            if int(game.get("gamePk") or -1) == int(exclude_game_pk):
                continue
            status = game.get("status") or {}
            detailed = str(status.get("detailedState") or "").lower()
            abstract = str(status.get("abstractGameState") or "").lower()
            if "final" not in detailed and "final" not in abstract and "completed" not in detailed:
                continue
            rows.append((days_ago, game))
    return sorted(rows, key=lambda item: (item[0], int(item[1].get("gamePk") or 0)))


def _assign_lineup_aggregate(context: PregameContext, side: str, aggregate: Any) -> None:
    setattr(context, f"{side}_lineup_obp", aggregate.on_base_percentage)
    setattr(context, f"{side}_lineup_slg", aggregate.slugging_percentage)
    setattr(context, f"{side}_lineup_ops", aggregate.ops)
    setattr(context, f"{side}_lineup_woba_proxy", aggregate.woba_proxy)
    setattr(context, f"{side}_lineup_iso", aggregate.isolated_power)
    setattr(context, f"{side}_lineup_bb_rate", aggregate.walk_rate)
    setattr(context, f"{side}_lineup_k_rate", aggregate.strikeout_rate)
    setattr(context, f"{side}_lineup_stats_coverage", aggregate.coverage)


def enrich_advanced_context(
    context: PregameContext,
    *,
    client: Any,
    season: int,
    capture_time: datetime,
    snapshot_store: ImmutableSnapshotStore,
    hitter_cache: dict[int, dict[str, Any]],
    team_stats_cache: dict[tuple[int, str], dict[str, Any]],
    venue_cache: dict[int, dict[str, Any]],
    recent_schedule_cache: dict[int, dict[str, Any]],
    live_feed_cache: dict[int, dict[str, Any]],
) -> PregameContext:
    """Collect optional point-in-time context while failing closed on unavailable feeds.

    The official schedule/live/starter capture remains mandatory. Every advanced source
    is optional and separately marked in provenance, so an unavailable endpoint never
    creates a fabricated value or prevents a valid baseline prediction.
    """

    raw_sources: dict[str, Any] = {}

    weather = derive_weather_features(
        temperature_f=context.temperature_f,
        wind_description=context.wind_description,
        roof_status=context.roof_status,
        condition=context.weather_condition,
    )
    for name in ("weather_run_factor", "air_density", "wind_out_component", "rain_risk"):
        setattr(context, name, weather.get(name))
    context.provenance["weather_park"] = "mlb_stats_api:live_feed:derived_bounded_proxy"
    raw_sources["weather_normalized"] = weather

    for side in ("away", "home"):
        lineup_ids = list(getattr(context, f"{side}_lineup_ids"))
        lineup_payloads: list[dict[str, Any] | None] = []
        if lineup_ids:
            lineup_ids = lineup_ids[:9]
            uncached = [person_id for person_id in lineup_ids if person_id not in hitter_cache]
            if uncached:
                batch = _optional_client_call(
                    client, "people_hitting_stats", uncached, int(season)
                )
                hitter_cache.update(_people_hitting_payloads(batch))
            for person_id in lineup_ids:
                if person_id not in hitter_cache:
                    payload = _optional_client_call(
                        client, "person_hitting_stats", int(person_id), int(season)
                    )
                    if payload is not None:
                        hitter_cache[person_id] = payload
                lineup_payloads.append(hitter_cache.get(person_id))
            aggregate = aggregate_lineup_stats(lineup_payloads)
            _assign_lineup_aggregate(context, side, aggregate)
            raw_sources[f"{side}_lineup_stats"] = {
                "person_ids": lineup_ids[:9],
                "payloads": lineup_payloads,
                "aggregate": aggregate.__dict__,
            }
            context.provenance[f"lineup_stats_{side}"] = (
                "mlb_stats_api:v1/people/stats:season:hitting"
                if aggregate.valid_player_count
                else "mlb_stats_api:lineup_posted_stats_unavailable"
            )
        else:
            context.provenance[f"lineup_stats_{side}"] = "mlb_stats_api:lineup_not_posted"

        team_id = getattr(context, f"{side}_team_id")
        if team_id is None:
            continue
        for group in ("pitching", "fielding"):
            key = (int(team_id), group)
            if key not in team_stats_cache:
                payload = _optional_client_call(client, "team_stats", int(team_id), int(season), group)
                if payload is not None:
                    team_stats_cache[key] = payload
            payload = team_stats_cache.get(key)
            if payload is None:
                context.provenance[f"team_{group}_{side}"] = "mlb_stats_api:unavailable"
                continue
            raw_sources[f"{side}_team_{group}"] = payload
            if group == "pitching":
                parsed = parse_team_pitching_stats(payload)
                setattr(context, f"{side}_bullpen_era_proxy", parsed["era"])
                setattr(context, f"{side}_bullpen_whip_proxy", parsed["whip"])
            else:
                parsed = parse_team_fielding_stats(payload)
                setattr(context, f"{side}_defense_fielding_pct", parsed["fielding_percentage"])
                setattr(context, f"{side}_defense_errors_per_game", parsed["errors_per_game"])
            context.provenance[f"team_{group}_{side}"] = (
                f"mlb_stats_api:v1/teams/{int(team_id)}/stats:season:{group}"
            )

        if int(team_id) not in recent_schedule_cache:
            payload = _optional_client_call(
                client, "recent_team_schedule", int(team_id), context.game_date, 4
            )
            if payload is not None:
                recent_schedule_cache[int(team_id)] = payload
        recent_schedule = recent_schedule_cache.get(int(team_id))
        recent_games = _recent_completed_games(
            recent_schedule,
            target_date=context.game_date,
            exclude_game_pk=int(context.game_pk or -1),
        )
        recent_feeds: list[tuple[int, dict[str, Any]]] = []
        for days_ago, game in recent_games[:4]:
            game_pk = game.get("gamePk")
            if game_pk is None:
                continue
            if int(game_pk) not in live_feed_cache:
                payload = _optional_client_call(client, "live_feed", int(game_pk))
                if payload is not None:
                    live_feed_cache[int(game_pk)] = payload
            feed = live_feed_cache.get(int(game_pk))
            if feed is not None:
                recent_feeds.append((days_ago, feed))
        usage = parse_recent_bullpen_usage(recent_feeds, team_id=int(team_id))
        setattr(context, f"{side}_bullpen_recent_pitches", usage.relief_pitches_weighted)
        setattr(context, f"{side}_bullpen_recent_innings", usage.relief_innings_weighted)
        setattr(context, f"{side}_bullpen_fatigue", usage.fatigue)
        setattr(context, f"{side}_closer_available", usage.closer_available)
        raw_sources[f"{side}_recent_schedule"] = recent_schedule
        raw_sources[f"{side}_recent_game_feeds"] = recent_feeds
        raw_sources[f"{side}_bullpen_usage"] = usage.__dict__
        context.provenance[f"bullpen_usage_{side}"] = (
            "mlb_stats_api:recent_live_feeds"
            if usage.games_observed
            else "mlb_stats_api:no_completed_recent_games"
        )

        previous_venue_payload = None
        previous_game = recent_games[0][1] if recent_games else None
        previous_venue_id = int(((previous_game or {}).get("venue") or {}).get("id") or 0)
        current_venue_id = int(context.venue_id or 0)
        if current_venue_id:
            if current_venue_id not in venue_cache:
                payload = _optional_client_call(client, "venue", current_venue_id)
                if payload is not None:
                    venue_cache[current_venue_id] = payload
            current_venue_payload = venue_cache.get(current_venue_id)
        else:
            current_venue_payload = None
        if previous_venue_id:
            if previous_venue_id not in venue_cache:
                payload = _optional_client_call(client, "venue", previous_venue_id)
                if payload is not None:
                    venue_cache[previous_venue_id] = payload
            previous_venue_payload = venue_cache.get(previous_venue_id)
        if current_venue_payload and previous_venue_payload:
            current_venue = parse_venue_location(current_venue_payload)
            previous_venue = parse_venue_location(previous_venue_payload)
            rest_days = float(recent_games[0][0] + 1) if recent_games else None
            travel = derive_travel_load(
                previous_venue=previous_venue,
                current_venue=current_venue,
                rest_days=rest_days,
                games_last3=float(sum(days_ago <= 2 for days_ago, _ in recent_games)),
            )
            setattr(context, f"{side}_travel_fatigue", travel.fatigue)
            setattr(context, f"{side}_time_zones_crossed", travel.time_zones_crossed)
            raw_sources[f"{side}_travel"] = {
                "previous_venue": previous_venue.__dict__,
                "current_venue": current_venue.__dict__,
                "load": travel.__dict__,
            }
            context.provenance[f"travel_{side}"] = "mlb_stats_api:venue+recent_schedule"
        else:
            context.provenance[f"travel_{side}"] = "mlb_stats_api:venue_context_unavailable"

    payload = advanced_snapshot_payload(context, raw_sources)
    advanced_path = snapshot_store.write(
        kind="mlb_advanced_pregame",
        captured_at=capture_time,
        payload=payload,
        source="mlb_stats_api:multi_endpoint_advanced_context",
        identity=str(int(context.game_pk)),
    )
    advanced_digest = sha256(advanced_path.read_bytes()).hexdigest()
    context.advanced_snapshot_path = str(advanced_path)
    context.advanced_snapshot_sha256 = advanced_digest
    context.provenance["advanced_context"] = (
        f"mlb_stats_api:multi_endpoint:sha256:{advanced_digest}"
    )
    return context


def context_to_external_feature_record(context: PregameContext) -> dict[str, Any]:
    """Map a live context into the V2 difference-style feature contract.

    These fields are included for forward compatibility and snapshot collection. The
    current historical V2 training rows leave most advanced fields missing, so callers
    must not claim that every populated field affects today's fitted probability.
    """

    def diff(away: float | None, home: float | None, team_a_is_away: bool) -> float | None:
        if away is None or home is None:
            return None
        return away - home if team_a_is_away else home - away

    team_a_is_away = context.away_team < context.home_team
    record: dict[str, Any] = {
        "date": context.game_date,
        "game_pk": context.game_pk,
        "away_team": context.away_team,
        "home_team": context.home_team,
        "lineup_confirmed": float(context.lineups_confirmed),
    }
    paired_fields = {
        "starter_fip": (context.away_starter_fip, context.home_starter_fip),
        "starter_k_minus_bb": (context.away_k_minus_bb, context.home_k_minus_bb),
        "starter_xera": (context.away_starter_xera, context.home_starter_xera),
        "starter_xfip": (context.away_starter_xfip, context.home_starter_xfip),
        "starter_siera": (context.away_starter_siera, context.home_starter_siera),
        "lineup_obp": (context.away_lineup_obp, context.home_lineup_obp),
        "lineup_slg": (context.away_lineup_slg, context.home_lineup_slg),
        "lineup_ops": (context.away_lineup_ops, context.home_lineup_ops),
        "lineup_woba_proxy": (
            context.away_lineup_woba_proxy,
            context.home_lineup_woba_proxy,
        ),
        "lineup_iso": (context.away_lineup_iso, context.home_lineup_iso),
        "lineup_bb_rate": (context.away_lineup_bb_rate, context.home_lineup_bb_rate),
        "lineup_k_rate": (context.away_lineup_k_rate, context.home_lineup_k_rate),
        "lineup_stats_coverage": (
            context.away_lineup_stats_coverage,
            context.home_lineup_stats_coverage,
        ),
        "injury_war": (context.away_injury_war, context.home_injury_war),
        "bullpen_xfip": (context.away_bullpen_xfip, context.home_bullpen_xfip),
        "bullpen_siera": (context.away_bullpen_siera, context.home_bullpen_siera),
        "bullpen_era_proxy": (
            context.away_bullpen_era_proxy,
            context.home_bullpen_era_proxy,
        ),
        "bullpen_whip_proxy": (
            context.away_bullpen_whip_proxy,
            context.home_bullpen_whip_proxy,
        ),
        "bullpen_recent_pitches": (
            context.away_bullpen_recent_pitches,
            context.home_bullpen_recent_pitches,
        ),
        "bullpen_recent_innings": (
            context.away_bullpen_recent_innings,
            context.home_bullpen_recent_innings,
        ),
        "bullpen_fatigue": (
            context.away_bullpen_fatigue,
            context.home_bullpen_fatigue,
        ),
        "closer_available": (
            context.away_closer_available,
            context.home_closer_available,
        ),
        "travel_fatigue": (
            context.away_travel_fatigue,
            context.home_travel_fatigue,
        ),
        "time_zones_crossed": (
            context.away_time_zones_crossed,
            context.home_time_zones_crossed,
        ),
        "defense_frv": (context.away_defense_frv, context.home_defense_frv),
        "defense_oaa": (context.away_defense_oaa, context.home_defense_oaa),
        "defense_fielding_pct": (
            context.away_defense_fielding_pct,
            context.home_defense_fielding_pct,
        ),
        "defense_errors_per_game": (
            context.away_defense_errors_per_game,
            context.home_defense_errors_per_game,
        ),
        "catcher_framing": (
            context.away_catcher_framing,
            context.home_catcher_framing,
        ),
        "baserunning_runs": (
            context.away_baserunning_runs,
            context.home_baserunning_runs,
        ),
    }
    for name, (away_value, home_value) in paired_fields.items():
        value = diff(away_value, home_value, team_a_is_away)
        if value is not None:
            record[f"{name}_diff"] = value

    for name in (
        "umpire_run_factor",
        "umpire_k_factor",
        "park_run_factor",
        "park_hr_factor",
        "weather_run_factor",
        "air_density",
        "wind_out_component",
        "rain_risk",
        "reverse_line_move",
    ):
        value = getattr(context, name)
        if value is not None:
            record[name] = float(value)
    return record


def capture_live_slate(
    *,
    game_date: str,
    client: MLBStatsHTTPClient,
    snapshot_store: ImmutableSnapshotStore,
    captured_at: datetime | None = None,
) -> tuple[Path, list[Path], list[PregameContext]]:
    """Fetch and freeze official schedule, starter, and pregame context snapshots.

    Starting-pitcher source payloads are written as separate immutable snapshots before
    they are summarized into the game context. This preserves the exact public payload,
    official person identity, capture time, and scheduled start for future retraining.
    """

    capture_time = captured_at or datetime.now(timezone.utc)
    if capture_time.tzinfo is None or capture_time.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    capture_time = capture_time.astimezone(timezone.utc)
    schedule_payload = client.schedule(game_date)
    schedule_path = snapshot_store.write_schedule(
        raw_payload=schedule_payload,
        captured_at=capture_time,
        source="mlb_stats_api:v1/schedule",
    )
    contexts: list[PregameContext] = []
    paths: list[Path] = []
    season = int(game_date[:4])
    identity_source = "mlb_stats_api:v1/schedule+v1.1/game/feed/live"
    stats_source = "mlb_stats_api:v1/people/stats:season"
    hitter_cache: dict[int, dict[str, Any]] = {}
    team_stats_cache: dict[tuple[int, str], dict[str, Any]] = {}
    venue_cache: dict[int, dict[str, Any]] = {}
    recent_schedule_cache: dict[int, dict[str, Any]] = {}
    live_feed_cache: dict[int, dict[str, Any]] = {}

    for record in parse_mlb_schedule(schedule_payload):
        context = PregameContext(
            game_date=record.official_date,
            away_team=record.away_team_abbreviation or record.away_team_name,
            home_team=record.home_team_abbreviation or record.home_team_name,
            game_pk=record.game_pk,
            game_datetime=record.game_datetime,
            game_number=record.game_number,
            double_header=record.double_header,
            status_abstract=record.status_abstract,
            status_detailed=record.status_detailed,
            venue_id=record.venue_id,
            venue_name=record.venue_name,
            away_team_id=record.away_team_id,
            home_team_id=record.home_team_id,
            away_probable_pitcher_id=record.away_probable_pitcher_id,
            home_probable_pitcher_id=record.home_probable_pitcher_id,
            away_probable_pitcher_name=record.away_probable_pitcher_name,
            home_probable_pitcher_name=record.home_probable_pitcher_name,
        )
        feed = client.live_feed(record.game_pk)
        live_feed_cache[int(record.game_pk)] = feed
        enrich_context_from_live_feed(context, feed)
        game_start = datetime.fromisoformat(record.game_datetime.replace("Z", "+00:00"))

        away_stats: dict[str, Any] = {}
        home_stats: dict[str, Any] = {}
        context.provenance.update(
            {
                "schedule": "mlb_stats_api:v1/schedule",
                "live_feed": "mlb_stats_api:v1.1/game/feed/live",
                "starter_identity": identity_source,
                "pitcher_stats": f"{stats_source}:immutable_snapshot",
            }
        )

        if capture_time <= game_start:
            for side in ("away", "home"):
                pitcher_id = getattr(context, f"{side}_probable_pitcher_id")
                pitcher_name = getattr(context, f"{side}_probable_pitcher_name")
                team_id = getattr(context, f"{side}_team_id")
                if pitcher_id is None or team_id is None:
                    context.provenance[f"starter_stats_{side}"] = (
                        "mlb_stats_api:not_posted_before_capture"
                    )
                    continue
                raw_stats = client.person_pitching_stats(int(pitcher_id), season)
                starter_payload = build_starter_snapshot_payload(
                    game_pk=record.game_pk,
                    scheduled_start=record.game_datetime,
                    side=side,
                    team_id=int(team_id),
                    pitcher_id=int(pitcher_id),
                    pitcher_name=pitcher_name,
                    season=season,
                    identity_source=identity_source,
                    raw_payload=raw_stats,
                )
                starter_path = snapshot_store.write_starter_pregame(
                    game_pk=record.game_pk,
                    game_datetime=record.game_datetime,
                    side=side,
                    pitcher_id=int(pitcher_id),
                    payload=starter_payload,
                    captured_at=capture_time,
                    source=stats_source,
                )
                starter_digest = sha256(starter_path.read_bytes()).hexdigest()
                setattr(context, f"{side}_starter_stats_snapshot_path", str(starter_path))
                setattr(
                    context,
                    f"{side}_starter_stats_snapshot_sha256",
                    starter_digest,
                )
                context.provenance[f"starter_stats_{side}"] = (
                    f"{stats_source}:sha256:{starter_digest}"
                )
                if side == "away":
                    away_stats = raw_stats
                else:
                    home_stats = raw_stats

            apply_pitcher_stats_to_context(
                context, away_payload=away_stats, home_payload=home_stats
            )
            enrich_advanced_context(
                context,
                client=client,
                season=season,
                capture_time=capture_time,
                snapshot_store=snapshot_store,
                hitter_cache=hitter_cache,
                team_stats_cache=team_stats_cache,
                venue_cache=venue_cache,
                recent_schedule_cache=recent_schedule_cache,
                live_feed_cache=live_feed_cache,
            )
            path = snapshot_store.write_pregame(
                game_pk=record.game_pk,
                game_datetime=record.game_datetime,
                context_payload=context.to_record(),
                captured_at=capture_time,
                source="mlb_stats_api_live_capture",
            )
            paths.append(path)
        else:
            context.provenance["starter_stats_away"] = "not_captured_after_start"
            context.provenance["starter_stats_home"] = "not_captured_after_start"

        contexts.append(context)
    return schedule_path, paths, contexts


def _logit(probability: float) -> float:
    p = float(np.clip(probability, 1e-8, 1 - 1e-8))
    return math.log(p / (1 - p))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(np.clip(value, -30, 30))))


def _confidence_score(probability: float, overlap: int, model_count: int) -> float:
    probability_strength = 2.0 * abs(probability - 0.5)
    overlap_rate = overlap / model_count if model_count else 0.0
    return 0.70 * probability_strength + 0.30 * overlap_rate


def evaluate_live_slate(
    *,
    historical_features: pd.DataFrame,
    future_features: pd.DataFrame,
    moneylines: list[ManualMoneyline],
    config: LiveEvaluationConfig | None = None,
    simulation_draws: MutableMapping[int, tuple[np.ndarray, np.ndarray]] | None = None,
) -> pd.DataFrame:
    """Evaluate every supplied game and rank picks by model confidence.

    The engine fits the seven-model ensemble and Poisson score model, runs the requested
    Monte Carlo simulations, and reports probabilities, score expectations, model
    agreement, fair odds, and market edges. It does not size wagers or manage a bankroll.
    """

    config = config or LiveEvaluationConfig()
    if future_features.empty:
        raise ValueError("future_features cannot be empty")
    if len(moneylines) != len(future_features):
        raise ValueError("moneylines and future_features must contain the same number of games")

    odds_by_pk = {line.game_pk: line for line in moneylines if line.game_pk is not None}
    odds_by_match = {
        (line.game_date, line.away_team, line.home_team): line for line in moneylines
    }

    model = V2Ensemble().fit(historical_features)
    score_model = PoissonScoreModel().fit(historical_features)
    model_probability_a, components = model.predict_proba(future_features)
    group_sensitivities_a = model.group_sensitivities(future_features)
    expected_runs_a, expected_runs_b = score_model.expected_runs(future_features)
    rng = np.random.default_rng(RANDOM_SEED)
    rows: list[dict[str, Any]] = []

    for idx, (_, feature_row) in enumerate(future_features.iterrows()):
        environment_factor = 1.0
        for name in ("weather_run_factor", "park_run_factor"):
            value = feature_row.get(f"live_{name}", 0.0)
            missing = feature_row.get(f"missing_{name}", 1.0)
            if float(missing) < 0.5 and value is not None and np.isfinite(float(value)):
                numeric = float(value)
                if numeric > 0.0:
                    environment_factor *= numeric
        environment_factor = float(np.clip(environment_factor, 0.80, 1.20))
        simulation_kwargs = {"return_draws": True} if simulation_draws is not None else {}
        simulation = simulate_poisson_score_distribution(
            expected_runs_a[idx] * environment_factor,
            expected_runs_b[idx] * environment_factor,
            config.simulations,
            rng,
            **simulation_kwargs,
        )
        score_p_a = simulation["team_a_win_probability"]
        blended_a = (
            (1.0 - config.score_simulation_weight) * float(model_probability_a[idx])
            + config.score_simulation_weight * score_p_a
        )
        # Keep the same explicit Monte Carlo finalization used by V2 replay_dates.
        finalized_a = float(rng.binomial(1, blended_a, config.simulations).mean())
        if config.home_field_logit_adjustment:
            direction = 1.0 if float(feature_row.get("team_a_is_home", 0.0)) >= 0.5 else -1.0
            finalized_a = _sigmoid(_logit(finalized_a) + direction * config.home_field_logit_adjustment)

        away = str(feature_row["away_team"])
        home = str(feature_row["home_team"])
        team_a = str(feature_row["team_a"])
        team_b = str(feature_row["team_b"])
        team_a_is_away = team_a == away
        away_probability = finalized_a if team_a_is_away else 1.0 - finalized_a
        home_probability = 1.0 - away_probability

        component_a = {name: float(values[idx]) for name, values in components.items()}
        component_away = {
            name: (prob if team_a_is_away else 1.0 - prob) for name, prob in component_a.items()
        }
        pick = away if away_probability >= home_probability else home
        pick_probability = max(away_probability, home_probability)
        pick_is_away = pick == away

        pick_group_sensitivities: dict[str, float] = {}
        for group_name, values in group_sensitivities_a.items():
            effect_a = float(values[idx])
            effect_away = effect_a if team_a_is_away else -effect_a
            pick_group_sensitivities[group_name] = (
                effect_away if pick_is_away else -effect_away
            )
        supporting = [
            (name, value) for name, value in pick_group_sensitivities.items() if value > 0.0
        ]
        opposing = [
            (name, value) for name, value in pick_group_sensitivities.items() if value < 0.0
        ]
        top_supporting_group, top_supporting_sensitivity = (
            max(supporting, key=lambda item: item[1]) if supporting else (None, 0.0)
        )
        top_opposing_group, top_opposing_sensitivity = (
            min(opposing, key=lambda item: item[1]) if opposing else (None, 0.0)
        )

        votes_pick = sum(
            (prob >= 0.5) if pick_is_away else (prob < 0.5)
            for prob in component_away.values()
        )
        model_count = len(component_away)

        game_pk = feature_row.get("game_pk")
        line = None
        if game_pk is not None and pd.notna(game_pk):
            line = odds_by_pk.get(int(game_pk))
        if line is None:
            line = odds_by_match.get((str(feature_row["date"].date()), away, home))
        if line is None:
            raise KeyError(f"No moneyline supplied for {away}@{home}")
        if simulation_draws is not None:
            if game_pk is None or pd.isna(game_pk):
                raise ValueError("simulation snapshots require an official game_pk")
            team_a_runs = np.asarray(simulation["team_a_runs"], dtype=np.int16)
            team_b_runs = np.asarray(simulation["team_b_runs"], dtype=np.int16)
            away_runs = team_a_runs if team_a_is_away else team_b_runs
            home_runs = team_b_runs if team_a_is_away else team_a_runs
            simulation_draws[int(game_pk)] = (away_runs.copy(), home_runs.copy())

        away_market, home_market = no_vig_probabilities(line.away_odds, line.home_odds)
        pick_odds = line.away_odds if pick_is_away else line.home_odds
        pick_no_vig = away_market if pick_is_away else home_market
        pick_break_even = american_implied_probability(pick_odds)
        # Score means are mapped back from canonical team_a/team_b to away/home.
        a_mean = simulation["team_a_mean_runs"]
        b_mean = simulation["team_b_mean_runs"]
        away_mean = a_mean if team_a_is_away else b_mean
        home_mean = b_mean if team_a_is_away else a_mean

        def oriented_last_value(name: str) -> tuple[float, float]:
            diff_value = float(feature_row.get(f"{name}_diff", 0.0))
            sum_value = float(feature_row.get(f"{name}_sum", 0.0))
            a_value = 0.5 * (sum_value + diff_value)
            b_value = 0.5 * (sum_value - diff_value)
            return (a_value, b_value) if team_a_is_away else (b_value, a_value)

        away_last_win, home_last_win = oriented_last_value("last_win")
        away_last_rf, home_last_rf = oriented_last_value("last_rf")
        away_last_ra, home_last_ra = oriented_last_value("last_ra")
        away_last_rd, home_last_rd = oriented_last_value("last_rd")
        away_last_blowout_loss, home_last_blowout_loss = oriented_last_value("last_blowout_loss")
        away_last_was_shutout, home_last_was_shutout = oriented_last_value("last_was_shutout")

        row = {
            "game_date": str(feature_row["date"].date()),
            "game_pk": int(game_pk) if game_pk is not None and pd.notna(game_pk) else None,
            "away_team": away,
            "home_team": home,
            "away_odds": line.away_odds,
            "home_odds": line.home_odds,
            "pick": pick,
            "pick_odds": pick_odds,
            "pick_probability": pick_probability,
            "away_probability": away_probability,
            "home_probability": home_probability,
            "model_overlap": votes_pick,
            "model_count": model_count,
            "confidence_score": _confidence_score(pick_probability, votes_pick, model_count),
            "simulated_away_runs": away_mean,
            "simulated_home_runs": home_mean,
            "score_sim_away_probability": score_p_a if team_a_is_away else 1.0 - score_p_a,
            "no_vig_pick_probability": pick_no_vig,
            "break_even_probability": pick_break_even,
            "edge_vs_no_vig": pick_probability - pick_no_vig,
            "edge_vs_break_even": pick_probability - pick_break_even,
            "fair_odds": probability_to_american(pick_probability),
            "lineups_confirmed": bool(feature_row.get("lineups_confirmed", False)),
            "top_supporting_group": top_supporting_group,
            "top_supporting_sensitivity": top_supporting_sensitivity,
            "top_opposing_group": top_opposing_group,
            "top_opposing_sensitivity": top_opposing_sensitivity,
            "attribution_scope": "seven_model_ensemble_before_score_blend",
            "attribution_method": "leave_one_group_at_training_median_non_additive",
            "away_last_win": away_last_win,
            "away_last_runs_for": away_last_rf,
            "away_last_runs_against": away_last_ra,
            "away_last_run_diff": away_last_rd,
            "away_last_blowout_loss": away_last_blowout_loss,
            "away_last_was_shutout": away_last_was_shutout,
            "home_last_win": home_last_win,
            "home_last_runs_for": home_last_rf,
            "home_last_runs_against": home_last_ra,
            "home_last_run_diff": home_last_rd,
            "home_last_blowout_loss": home_last_blowout_loss,
            "home_last_was_shutout": home_last_was_shutout,
            "simulations": config.simulations,
            "environment_run_factor": environment_factor,
        }
        row.update({f"p_{name}_{away}": prob for name, prob in component_away.items()})
        row.update({
            f"ensemble_pick_sensitivity_{name}": value
            for name, value in pick_group_sensitivities.items()
        })
        rows.append(row)

    frame = pd.DataFrame(rows)
    return apply_selection_policy(
        frame,
        top_n=config.top_n,
        policy=config.selection_policy,
    )



def evaluate_top_pick_parlays(
    evaluations: pd.DataFrame,
    *,
    max_legs: int = 2,
    simulations: int = 100_000,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Evaluate simple top-pick parlays under an explicit independence assumption."""

    if max_legs != 2:
        raise NotImplementedError("only two-leg parlays are currently supported")
    top = evaluations[evaluations["is_top_pick"]].copy()
    rng = np.random.default_rng(seed)
    output: list[dict[str, Any]] = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            left = top.iloc[i]
            right = top.iloc[j]
            left_draw = rng.binomial(1, float(left.pick_probability), simulations)
            right_draw = rng.binomial(1, float(right.pick_probability), simulations)
            joint = float(np.mean((left_draw == 1) & (right_draw == 1)))
            odds = combine_american_odds([int(left.pick_odds), int(right.pick_odds)])
            output.append({
                "legs": f"{left.pick} {int(left.pick_odds):+d} + {right.pick} {int(right.pick_odds):+d}",
                "combined_odds": odds,
                "joint_probability": joint,
                "break_even_probability": american_implied_probability(odds),
                "edge_vs_break_even": joint - american_implied_probability(odds),
                "assumption": "independent_game_outcomes",
                "simulations": simulations,
            })
    if not output:
        return pd.DataFrame()
    return pd.DataFrame(output).sort_values(
        ["edge_vs_break_even", "joint_probability"], ascending=[False, False]
    ).reset_index(drop=True)


def load_manual_moneylines(path: str | Path) -> list[ManualMoneyline]:
    """Backward-compatible alias for the CSV/JSON user-input loader."""

    return load_moneylines(path)


def contexts_to_matchups(contexts: list[PregameContext]) -> pd.DataFrame:
    rows = []
    for context in contexts:
        rows.append({
            "date": context.game_date,
            "game_pk": context.game_pk,
            "game_datetime": context.game_datetime,
            "away_team": context.away_team,
            "home_team": context.home_team,
            "away_starter": context.away_probable_pitcher_name or "Unknown",
            "home_starter": context.home_probable_pitcher_name or "Unknown",
            "venue_name": context.venue_name,
            "lineups_confirmed": context.lineups_confirmed,
        })
    return pd.DataFrame(rows)


def write_evaluation_artifacts(
    evaluations: pd.DataFrame,
    *,
    output_dir: str | Path,
    stem: str,
    parlays: pd.DataFrame | None = None,
) -> tuple[Path, Path | None, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / f"{stem}.csv"
    json_path = directory / f"{stem}.json"
    evaluations.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(evaluations.to_dict("records"), indent=2, default=str),
        encoding="utf-8",
    )
    parlay_path = None
    if parlays is not None and not parlays.empty:
        parlay_path = directory / f"{stem}_parlays.csv"
        parlays.to_csv(parlay_path, index=False)
    return csv_path, parlay_path, json_path
