from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


_WIND_RE = re.compile(r"(?P<mph>\d+(?:\.\d+)?)\s*mph", re.IGNORECASE)


@dataclass(frozen=True)
class HitterSeasonLine:
    plate_appearances: float | None = None
    batting_average: float | None = None
    on_base_percentage: float | None = None
    slugging_percentage: float | None = None
    ops: float | None = None
    isolated_power: float | None = None
    walk_rate: float | None = None
    strikeout_rate: float | None = None
    woba_proxy: float | None = None


@dataclass(frozen=True)
class LineupAggregate:
    player_count: int
    valid_player_count: int
    plate_appearances: float
    coverage: float
    on_base_percentage: float | None
    slugging_percentage: float | None
    ops: float | None
    isolated_power: float | None
    walk_rate: float | None
    strikeout_rate: float | None
    woba_proxy: float | None


@dataclass(frozen=True)
class BullpenUsage:
    relief_pitches_weighted: float | None
    relief_innings_weighted: float | None
    reliever_appearances_weighted: float | None
    high_leverage_pitches_yesterday: float | None
    fatigue: float | None
    closer_available: float | None
    games_observed: int


@dataclass(frozen=True)
class VenueLocation:
    venue_id: int | None
    latitude: float | None
    longitude: float | None
    utc_offset_hours: float | None
    time_zone_id: str | None


@dataclass(frozen=True)
class TravelLoad:
    distance_miles: float | None
    time_zones_crossed: float | None
    fatigue: float | None


CONTEXT_FEATURE_NAMES: tuple[str, ...] = (
    "starter_fip_edge_home",
    "starter_kbb_edge_home",
    "starter_whip_edge_home",
    "lineup_ops_edge_home",
    "lineup_woba_edge_home",
    "lineup_k_rate_edge_home",
    "lineup_coverage_min",
    "bullpen_era_edge_home",
    "bullpen_fatigue_edge_home",
    "closer_availability_edge_home",
    "defense_fielding_edge_home",
    "defense_errors_edge_home",
    "travel_fatigue_edge_home",
    "injury_war_edge_home",
    "lineups_confirmed",
    "starters_confirmed",
)


def _first_stat_split(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for block in payload.get("stats", []) or []:
        splits = block.get("splits") or []
        if splits:
            stat = splits[0].get("stat")
            if isinstance(stat, Mapping):
                return stat
    return {}


def _finite_float(value: Any) -> float | None:
    if value in (None, "", "-", "-.--", ".---"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def parse_hitter_season_stats(payload: Mapping[str, Any]) -> HitterSeasonLine:
    """Parse a public MLB season-hitting payload without inventing Statcast fields.

    ``woba_proxy`` uses transparent public linear weights and is deliberately named a
    proxy. It must not be represented as Baseball Savant xwOBA or a season-specific
    official wOBA constant.
    """

    stat = _first_stat_split(payload)
    pa = _finite_float(stat.get("plateAppearances"))
    ab = _finite_float(stat.get("atBats"))
    hits = _finite_float(stat.get("hits"))
    doubles = _finite_float(stat.get("doubles"))
    triples = _finite_float(stat.get("triples"))
    homers = _finite_float(stat.get("homeRuns"))
    walks = _finite_float(stat.get("baseOnBalls"))
    intentional_walks = _finite_float(stat.get("intentionalWalks")) or 0.0
    strikeouts = _finite_float(stat.get("strikeOuts"))
    hbp = _finite_float(stat.get("hitByPitch"))
    sac_flies = _finite_float(stat.get("sacFlies"))

    avg = _finite_float(stat.get("avg"))
    obp = _finite_float(stat.get("obp"))
    slg = _finite_float(stat.get("slg"))
    ops = _finite_float(stat.get("ops"))
    if ops is None and obp is not None and slg is not None:
        ops = obp + slg
    iso = slg - avg if slg is not None and avg is not None else None
    walk_rate = _safe_rate(walks, pa)
    strikeout_rate = _safe_rate(strikeouts, pa)

    woba_proxy = None
    required = (ab, hits, doubles, triples, homers, walks, hbp, sac_flies)
    if all(value is not None for value in required):
        singles = max(0.0, float(hits) - float(doubles) - float(triples) - float(homers))
        denominator = float(ab) + float(walks) - intentional_walks + float(sac_flies) + float(hbp)
        if denominator > 0:
            numerator = (
                0.69 * max(0.0, float(walks) - intentional_walks)
                + 0.72 * float(hbp)
                + 0.88 * singles
                + 1.247 * float(doubles)
                + 1.578 * float(triples)
                + 2.031 * float(homers)
            )
            woba_proxy = numerator / denominator

    return HitterSeasonLine(
        plate_appearances=pa,
        batting_average=avg,
        on_base_percentage=obp,
        slugging_percentage=slg,
        ops=ops,
        isolated_power=iso,
        walk_rate=walk_rate,
        strikeout_rate=strikeout_rate,
        woba_proxy=woba_proxy,
    )


def aggregate_lineup_stats(
    player_payloads: Sequence[Mapping[str, Any] | None],
) -> LineupAggregate:
    lines = [parse_hitter_season_stats(payload or {}) for payload in player_payloads]
    valid = [line for line in lines if line.plate_appearances and line.plate_appearances > 0]
    total_pa = float(sum(line.plate_appearances or 0.0 for line in valid))

    def weighted(name: str) -> float | None:
        pairs = [
            (float(getattr(line, name)), float(line.plate_appearances or 0.0))
            for line in valid
            if getattr(line, name) is not None and (line.plate_appearances or 0.0) > 0
        ]
        total_weight = sum(weight for _, weight in pairs)
        return sum(value * weight for value, weight in pairs) / total_weight if total_weight else None

    count = len(player_payloads)
    return LineupAggregate(
        player_count=count,
        valid_player_count=len(valid),
        plate_appearances=total_pa,
        coverage=(len(valid) / count) if count else 0.0,
        on_base_percentage=weighted("on_base_percentage"),
        slugging_percentage=weighted("slugging_percentage"),
        ops=weighted("ops"),
        isolated_power=weighted("isolated_power"),
        walk_rate=weighted("walk_rate"),
        strikeout_rate=weighted("strikeout_rate"),
        woba_proxy=weighted("woba_proxy"),
    )


def parse_wind_description(description: str | None) -> tuple[float | None, float | None]:
    """Return wind speed and a signed outfield component.

    Positive values indicate wind described as blowing out, negative values indicate
    wind blowing in, and crosswinds are zero. Unknown direction remains missing.
    """

    if not description:
        return None, None
    match = _WIND_RE.search(description)
    speed = float(match.group("mph")) if match else None
    text = description.lower()
    if speed is None:
        return None, None
    if "out to" in text or "out toward" in text or "blowing out" in text:
        return speed, speed
    if "in from" in text or "blowing in" in text:
        return speed, -speed
    if "left to right" in text or "right to left" in text or "cross" in text:
        return speed, 0.0
    return speed, None


def derive_weather_features(
    *,
    temperature_f: float | None,
    wind_description: str | None,
    roof_status: str | None,
    condition: str | None,
) -> dict[str, float | None]:
    """Create transparent, bounded environment features from official game context.

    The run factor is an operational physics-informed proxy, not a learned causal
    coefficient. A closed roof or dome neutralizes outdoor temperature/wind inputs.
    """

    wind_speed, wind_out = parse_wind_description(wind_description)
    roof = (roof_status or "").strip().lower()
    closed = any(token in roof for token in ("closed", "dome", "indoor"))
    if closed:
        return {
            "weather_run_factor": 1.0,
            "air_density": 1.0,
            "wind_out_component": 0.0,
            "rain_risk": 0.0,
            "wind_speed_mph": wind_speed,
        }

    temp = temperature_f
    air_density = None
    factor = 1.0
    if temp is not None and math.isfinite(float(temp)):
        temp = float(temp)
        air_density = float(np.clip(1.0 - 0.0018 * (temp - 70.0), 0.90, 1.10))
        factor += 0.0025 * (temp - 70.0)
    if wind_out is not None:
        factor += 0.0040 * float(wind_out)

    condition_text = (condition or "").lower()
    rain_risk = 0.0
    if any(token in condition_text for token in ("rain", "shower", "drizzle", "storm")):
        rain_risk = 0.75
    elif any(token in condition_text for token in ("cloud", "overcast")):
        rain_risk = 0.15
    factor = float(np.clip(factor, 0.88, 1.12))
    return {
        "weather_run_factor": factor,
        "air_density": air_density,
        "wind_out_component": wind_out,
        "rain_risk": rain_risk,
        "wind_speed_mph": wind_speed,
    }


def _innings_to_outs(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value)
    try:
        whole, _, fraction = text.partition(".")
        outs = int(whole) * 3
        if fraction:
            digit = int(fraction[0])
            if digit not in {0, 1, 2}:
                return None
            outs += digit
        return outs
    except (TypeError, ValueError):
        return None


def parse_recent_bullpen_usage(
    feeds: Iterable[tuple[int, Mapping[str, Any]]],
    *,
    team_id: int,
) -> BullpenUsage:
    """Summarize recent reliever workload from immutable previous-game feeds.

    ``feeds`` contains ``(days_ago, live_feed)`` pairs. The first pitcher listed for a
    team is treated as the starter; subsequent pitchers are relievers. This is a
    transparent operational proxy and the raw feeds should be retained for audit.
    """

    weighted_pitches = 0.0
    weighted_outs = 0.0
    weighted_appearances = 0.0
    high_leverage_yesterday = 0.0
    observed = 0
    leverage_known = False

    for days_ago, feed in feeds:
        game_data = feed.get("gameData") or {}
        teams = game_data.get("teams") or {}
        side = None
        for candidate in ("away", "home"):
            if int(((teams.get(candidate) or {}).get("id") or -1)) == int(team_id):
                side = candidate
                break
        if side is None:
            continue
        team_box = (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}).get(side) or {}
        pitcher_ids = [int(value) for value in (team_box.get("pitchers") or [])]
        if len(pitcher_ids) <= 1:
            observed += 1
            continue
        players = team_box.get("players") or {}
        weight = {0: 1.0, 1: 0.65, 2: 0.35}.get(int(days_ago), 0.15)
        for pitcher_id in pitcher_ids[1:]:
            player = players.get(f"ID{pitcher_id}") or players.get(str(pitcher_id)) or {}
            pitching = ((player.get("stats") or {}).get("pitching") or {})
            pitches = _finite_float(pitching.get("numberOfPitches")) or 0.0
            outs = _innings_to_outs(pitching.get("inningsPitched")) or 0
            weighted_pitches += weight * pitches
            weighted_outs += weight * outs
            weighted_appearances += weight
            leverage_markers = sum(
                _finite_float(pitching.get(key)) or 0.0
                for key in ("saves", "holds", "blownSaves")
            )
            if leverage_markers > 0:
                leverage_known = True
                if int(days_ago) == 0:
                    high_leverage_yesterday += pitches
        observed += 1

    if observed == 0:
        return BullpenUsage(None, None, None, None, None, None, 0)

    fatigue = float(np.clip(weighted_pitches / 125.0, 0.0, 1.5))
    closer_available: float | None
    if not leverage_known:
        closer_available = None
    elif high_leverage_yesterday >= 30:
        closer_available = 0.0
    elif high_leverage_yesterday >= 20:
        closer_available = 0.35
    elif high_leverage_yesterday >= 10:
        closer_available = 0.75
    else:
        closer_available = 1.0
    return BullpenUsage(
        relief_pitches_weighted=weighted_pitches,
        relief_innings_weighted=weighted_outs / 3.0,
        reliever_appearances_weighted=weighted_appearances,
        high_leverage_pitches_yesterday=high_leverage_yesterday if leverage_known else None,
        fatigue=fatigue,
        closer_available=closer_available,
        games_observed=observed,
    )


def parse_team_pitching_stats(payload: Mapping[str, Any]) -> dict[str, float | None]:
    stat = _first_stat_split(payload)
    return {
        "era": _finite_float(stat.get("era")),
        "whip": _finite_float(stat.get("whip")),
        "k_per_9": _finite_float(stat.get("strikeoutsPer9Inn")),
        "bb_per_9": _finite_float(stat.get("walksPer9Inn")),
        "hr_per_9": _finite_float(stat.get("homeRunsPer9")),
    }


def parse_team_fielding_stats(payload: Mapping[str, Any]) -> dict[str, float | None]:
    stat = _first_stat_split(payload)
    games = _finite_float(stat.get("games"))
    errors = _finite_float(stat.get("errors"))
    return {
        "fielding_percentage": _finite_float(stat.get("fielding")),
        "errors_per_game": _safe_rate(errors, games),
        "range_factor_per_game": _finite_float(stat.get("rangeFactorPerGame")),
    }


def parse_venue_location(payload: Mapping[str, Any]) -> VenueLocation:
    venues = payload.get("venues") or []
    venue = venues[0] if venues else payload.get("venue") or payload
    location = venue.get("location") or {}
    coordinates = location.get("defaultCoordinates") or {}
    time_zone = venue.get("timeZone") or location.get("timeZone") or {}
    return VenueLocation(
        venue_id=int(venue["id"]) if venue.get("id") is not None else None,
        latitude=_finite_float(coordinates.get("latitude")),
        longitude=_finite_float(coordinates.get("longitude")),
        utc_offset_hours=_finite_float(time_zone.get("offset")),
        time_zone_id=str(time_zone.get("id")) if time_zone.get("id") else None,
    )


def haversine_miles(
    latitude_a: float | None,
    longitude_a: float | None,
    latitude_b: float | None,
    longitude_b: float | None,
) -> float | None:
    values = (latitude_a, longitude_a, latitude_b, longitude_b)
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, values))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.7613 * 2 * math.asin(math.sqrt(a))


def derive_travel_load(
    *,
    previous_venue: VenueLocation | None,
    current_venue: VenueLocation | None,
    rest_days: float | None,
    games_last3: float | None,
) -> TravelLoad:
    if previous_venue is None or current_venue is None:
        return TravelLoad(None, None, None)
    distance = haversine_miles(
        previous_venue.latitude,
        previous_venue.longitude,
        current_venue.latitude,
        current_venue.longitude,
    )
    zones = None
    if previous_venue.utc_offset_hours is not None and current_venue.utc_offset_hours is not None:
        zones = abs(current_venue.utc_offset_hours - previous_venue.utc_offset_hours)
    if distance is None and zones is None:
        return TravelLoad(None, zones, None)
    rest = 3.0 if rest_days is None else float(rest_days)
    density = 0.0 if games_last3 is None else float(games_last3)
    fatigue = (
        (0.0 if distance is None else min(distance / 2800.0, 1.0))
        + (0.0 if zones is None else min(zones / 3.0, 1.0)) * 0.45
        + max(0.0, 2.0 - rest) * 0.20
        + max(0.0, density - 2.0) * 0.15
    )
    return TravelLoad(distance, zones, float(np.clip(fatigue, 0.0, 1.5)))


def context_feature_vector(context: Any) -> dict[str, float]:
    """Create a fixed home-oriented vector for prospective online learning."""

    def edge_home(home: Any, away: Any, *, lower_is_better: bool = False) -> float:
        h = _finite_float(home)
        a = _finite_float(away)
        if h is None or a is None:
            return 0.0
        return (a - h) if lower_is_better else (h - a)

    away_coverage = _finite_float(getattr(context, "away_lineup_stats_coverage", None))
    home_coverage = _finite_float(getattr(context, "home_lineup_stats_coverage", None))
    coverage_values = [value for value in (away_coverage, home_coverage) if value is not None]
    vector = {
        "starter_fip_edge_home": edge_home(
            getattr(context, "home_starter_fip", None),
            getattr(context, "away_starter_fip", None),
            lower_is_better=True,
        ),
        "starter_kbb_edge_home": edge_home(
            getattr(context, "home_k_minus_bb", None),
            getattr(context, "away_k_minus_bb", None),
        ),
        "starter_whip_edge_home": edge_home(
            getattr(context, "home_starter_whip", None),
            getattr(context, "away_starter_whip", None),
            lower_is_better=True,
        ),
        "lineup_ops_edge_home": edge_home(
            getattr(context, "home_lineup_ops", None),
            getattr(context, "away_lineup_ops", None),
        ),
        "lineup_woba_edge_home": edge_home(
            getattr(context, "home_lineup_woba_proxy", None),
            getattr(context, "away_lineup_woba_proxy", None),
        ),
        "lineup_k_rate_edge_home": edge_home(
            getattr(context, "home_lineup_k_rate", None),
            getattr(context, "away_lineup_k_rate", None),
            lower_is_better=True,
        ),
        "lineup_coverage_min": min(coverage_values) if coverage_values else 0.0,
        "bullpen_era_edge_home": edge_home(
            getattr(context, "home_bullpen_era_proxy", None),
            getattr(context, "away_bullpen_era_proxy", None),
            lower_is_better=True,
        ),
        "bullpen_fatigue_edge_home": edge_home(
            getattr(context, "home_bullpen_fatigue", None),
            getattr(context, "away_bullpen_fatigue", None),
            lower_is_better=True,
        ),
        "closer_availability_edge_home": edge_home(
            getattr(context, "home_closer_available", None),
            getattr(context, "away_closer_available", None),
        ),
        "defense_fielding_edge_home": edge_home(
            getattr(context, "home_defense_fielding_pct", None),
            getattr(context, "away_defense_fielding_pct", None),
        ),
        "defense_errors_edge_home": edge_home(
            getattr(context, "home_defense_errors_per_game", None),
            getattr(context, "away_defense_errors_per_game", None),
            lower_is_better=True,
        ),
        "travel_fatigue_edge_home": edge_home(
            getattr(context, "home_travel_fatigue", None),
            getattr(context, "away_travel_fatigue", None),
            lower_is_better=True,
        ),
        "injury_war_edge_home": edge_home(
            getattr(context, "home_injury_war", None),
            getattr(context, "away_injury_war", None),
            lower_is_better=True,
        ),
        "lineups_confirmed": float(bool(getattr(context, "lineups_confirmed", False))),
        "starters_confirmed": float(bool(getattr(context, "probable_pitchers_confirmed", False))),
    }
    return {name: float(vector[name]) for name in CONTEXT_FEATURE_NAMES}


def advanced_snapshot_payload(context: Any, raw_sources: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        "game_pk": int(context.game_pk),
        "scheduled_start": str(context.game_datetime),
        "away_team": str(context.away_team),
        "home_team": str(context.home_team),
        "context_features_home_orientation": context_feature_vector(context),
        "weather_run_factor": getattr(context, "weather_run_factor", None),
        "park_run_factor": getattr(context, "park_run_factor", None),
        "away_lineup_stats_coverage": getattr(context, "away_lineup_stats_coverage", None),
        "home_lineup_stats_coverage": getattr(context, "home_lineup_stats_coverage", None),
    }
    raw_bytes = (json.dumps(raw_sources, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {
        **normalized,
        "raw_sources": dict(raw_sources),
        "raw_sources_sha256": sha256(raw_bytes).hexdigest(),
    }


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    body = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    temp.write_text(body, encoding="utf-8")
    temp.replace(target)
    return target


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
