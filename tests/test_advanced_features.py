from __future__ import annotations

from types import SimpleNamespace

import pytest

from supermodel.advanced_features import (
    aggregate_lineup_stats,
    context_feature_vector,
    derive_travel_load,
    derive_weather_features,
    parse_recent_bullpen_usage,
    parse_venue_location,
)


def _hitter(pa: int, *, avg: str, obp: str, slg: str, walks: int, strikeouts: int):
    hits = int(float(avg) * 300)
    return {
        "stats": [{"splits": [{"stat": {
            "plateAppearances": pa,
            "atBats": 300,
            "hits": hits,
            "doubles": 20,
            "triples": 2,
            "homeRuns": 15,
            "baseOnBalls": walks,
            "intentionalWalks": 1,
            "strikeOuts": strikeouts,
            "hitByPitch": 3,
            "sacFlies": 4,
            "avg": avg,
            "obp": obp,
            "slg": slg,
        }}]}]
    }


def test_lineup_aggregate_is_plate_appearance_weighted_and_tracks_coverage():
    result = aggregate_lineup_stats([
        _hitter(400, avg=".280", obp=".360", slg=".500", walks=45, strikeouts=70),
        _hitter(200, avg=".240", obp=".300", slg=".400", walks=20, strikeouts=60),
        None,
    ])
    assert result.player_count == 3
    assert result.valid_player_count == 2
    assert result.coverage == pytest.approx(2 / 3)
    assert result.on_base_percentage == pytest.approx((0.360 * 400 + 0.300 * 200) / 600)
    assert result.ops == pytest.approx((0.860 * 400 + 0.700 * 200) / 600)
    assert result.woba_proxy is not None


def test_weather_proxy_is_bounded_and_closed_roof_neutralizes_outdoor_inputs():
    open_air = derive_weather_features(
        temperature_f=95,
        wind_description="15 mph, Out To CF",
        roof_status="Open",
        condition="Partly Cloudy",
    )
    assert 1.0 < open_air["weather_run_factor"] <= 1.12
    assert open_air["wind_out_component"] == 15.0

    closed = derive_weather_features(
        temperature_f=95,
        wind_description="15 mph, Out To CF",
        roof_status="Closed",
        condition="Rain",
    )
    assert closed["weather_run_factor"] == 1.0
    assert closed["wind_out_component"] == 0.0
    assert closed["rain_risk"] == 0.0


def test_bullpen_usage_treats_baseball_innings_as_outs():
    away_box = {
        "pitchers": [1, 2, 3],
        "players": {
            "ID2": {
                "stats": {
                    "pitching": {
                        "numberOfPitches": 18,
                        "inningsPitched": "1.1",
                        "holds": 1,
                    }
                }
            },
            "ID3": {
                "stats": {
                    "pitching": {
                        "numberOfPitches": 12,
                        "inningsPitched": "0.2",
                        "saves": 1,
                    }
                }
            },
        },
    }
    feed = {
        "gameData": {"teams": {"away": {"id": 10}, "home": {"id": 20}}},
        "liveData": {
            "boxscore": {"teams": {"away": away_box, "home": {}}}
        },
    }
    result = parse_recent_bullpen_usage([(0, feed)], team_id=10)
    assert result.games_observed == 1
    assert result.relief_pitches_weighted == 30.0
    assert result.relief_innings_weighted == pytest.approx(2.0)
    assert result.closer_available == 0.0


def test_travel_load_uses_distance_time_zone_and_rest():
    previous = parse_venue_location({"venues": [{
        "id": 1,
        "location": {"defaultCoordinates": {"latitude": 34.05, "longitude": -118.25}},
        "timeZone": {"offset": -7, "id": "America/Los_Angeles"},
    }]})
    current = parse_venue_location({"venues": [{
        "id": 2,
        "location": {"defaultCoordinates": {"latitude": 40.71, "longitude": -74.01}},
        "timeZone": {"offset": -4, "id": "America/New_York"},
    }]})
    load = derive_travel_load(
        previous_venue=previous,
        current_venue=current,
        rest_days=0,
        games_last3=3,
    )
    assert load.distance_miles is not None and load.distance_miles > 2_000
    assert load.time_zones_crossed == 3
    assert load.fatigue is not None and load.fatigue > 1.0


def test_context_vector_is_home_oriented_and_missing_values_fail_neutral():
    context = SimpleNamespace(
        home_starter_fip=3.0,
        away_starter_fip=4.0,
        home_k_minus_bb=0.20,
        away_k_minus_bb=0.10,
        home_starter_whip=1.10,
        away_starter_whip=1.30,
        home_lineup_ops=0.800,
        away_lineup_ops=0.700,
        home_lineup_woba_proxy=0.340,
        away_lineup_woba_proxy=0.310,
        home_lineup_k_rate=0.20,
        away_lineup_k_rate=0.25,
        home_lineup_stats_coverage=1.0,
        away_lineup_stats_coverage=8 / 9,
        home_bullpen_era_proxy=3.5,
        away_bullpen_era_proxy=4.5,
        home_bullpen_fatigue=0.2,
        away_bullpen_fatigue=0.8,
        home_closer_available=1.0,
        away_closer_available=0.0,
        home_defense_fielding_pct=0.990,
        away_defense_fielding_pct=0.980,
        home_defense_errors_per_game=0.3,
        away_defense_errors_per_game=0.6,
        home_travel_fatigue=0.1,
        away_travel_fatigue=0.9,
        home_injury_war=None,
        away_injury_war=None,
        lineups_confirmed=True,
        away_probable_pitcher_id=1,
        home_probable_pitcher_id=2,
        probable_pitchers_confirmed=True,
    )
    vector = context_feature_vector(context)
    assert vector["starter_fip_edge_home"] == 1.0
    assert vector["lineup_ops_edge_home"] == pytest.approx(0.1)
    assert vector["bullpen_fatigue_edge_home"] == pytest.approx(0.6)
    assert vector["injury_war_edge_home"] == 0.0
    assert vector["lineups_confirmed"] == 1.0
    assert vector["starters_confirmed"] == 1.0
