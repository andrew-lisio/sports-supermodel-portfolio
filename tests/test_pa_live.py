from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from supermodel.game_registry import ImmutableSnapshotStore
from supermodel.pa_live import build_pa_game_inputs_from_context
from supermodel.pa_simulator import PAInputCoverageError, simulate_pa_games
from supermodel.providers import PregameContext
from supermodel.starter_features import build_starter_snapshot_payload


def _hitting_payload(player_offset: int) -> dict:
    return {
        "stats": [{"splits": [{"stat": {
            "plateAppearances": 400 + player_offset,
            "hits": 100 + player_offset // 2,
            "doubles": 22,
            "triples": 2,
            "homeRuns": 18,
            "baseOnBalls": 42,
            "hitByPitch": 4,
            "strikeOuts": 95,
        }}]}]
    }


def _pitching_payload(*, starts: int = 20, bf: int = 500) -> dict:
    return {
        "stats": [{"splits": [{"stat": {
            "gamesPlayed": starts,
            "gamesStarted": starts,
            "inningsPitched": "120.0",
            "era": "3.60",
            "whip": "1.20",
            "battersFaced": bf,
            "hits": 110,
            "homeRuns": 14,
            "baseOnBalls": 38,
            "hitBatsmen": 4,
            "strikeOuts": 130,
            "earnedRuns": 48,
            "groundOuts": 140,
            "airOuts": 100,
        }}]}]
    }


def _context(tmp_path: Path) -> PregameContext:
    game_pk = 123456
    scheduled = "2026-08-16T23:00:00Z"
    captured = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)
    context = PregameContext(
        game_date="2026-08-16",
        away_team="AWY",
        home_team="HOM",
        game_pk=game_pk,
        game_datetime=scheduled,
        probable_pitchers_confirmed=True,
        lineups_confirmed=True,
        away_team_id=1,
        home_team_id=2,
        away_probable_pitcher_id=11,
        home_probable_pitcher_id=22,
        away_probable_pitcher_name="Away Starter",
        home_probable_pitcher_name="Home Starter",
        away_lineup_ids=list(range(101, 110)),
        home_lineup_ids=list(range(201, 210)),
    )
    store = ImmutableSnapshotStore(tmp_path / "snapshots")
    raw_sources = {
        "away_lineup_stats": {
            "payloads": [_hitting_payload(i) for i in range(9)],
            "person_ids": context.away_lineup_ids,
        },
        "home_lineup_stats": {
            "payloads": [_hitting_payload(i + 10) for i in range(9)],
            "person_ids": context.home_lineup_ids,
        },
        "away_team_pitching": _pitching_payload(starts=60, bf=2200),
        "home_team_pitching": _pitching_payload(starts=60, bf=2200),
    }
    advanced = store.write(
        kind="mlb_advanced_pregame",
        captured_at=captured,
        payload={"game_pk": game_pk, "raw_sources": raw_sources},
        source="test",
        identity=str(game_pk),
    )
    context.advanced_snapshot_path = str(advanced)

    for side, team_id, pitcher_id in (("away", 1, 11), ("home", 2, 22)):
        raw = _pitching_payload()
        payload = build_starter_snapshot_payload(
            game_pk=game_pk,
            scheduled_start=scheduled,
            side=side,
            team_id=team_id,
            pitcher_id=pitcher_id,
            pitcher_name=f"{side} starter",
            season=2026,
            identity_source="test",
            raw_payload=raw,
        )
        path = store.write_starter_pregame(
            game_pk=game_pk,
            game_datetime=scheduled,
            side=side,
            pitcher_id=pitcher_id,
            payload=payload,
            captured_at=captured,
            source="test",
        )
        setattr(context, f"{side}_starter_stats_snapshot_path", str(path))
    return context


def test_live_adapter_fails_closed_without_confirmed_lineups(tmp_path: Path):
    context = _context(tmp_path)
    context.lineups_confirmed = False
    with pytest.raises(PAInputCoverageError, match="batting orders"):
        build_pa_game_inputs_from_context(context)


def test_live_adapter_builds_audited_partial_parity_inputs(tmp_path: Path):
    context = _context(tmp_path)
    inputs, audit = build_pa_game_inputs_from_context(context)
    assert audit.status == "PARTIAL_PARITY"
    assert "AWAY_BULLPEN_ALL_STAFF_PROXY" in audit.reasons
    assert "HOME_BULLPEN_ALL_STAFF_PROXY" in audit.reasons
    assert audit.away_lineup_coverage == 1.0
    assert audit.home_lineup_coverage == 1.0
    assert inputs.away_starter_expected_batters == 25.0
    assert inputs.home_starter_expected_batters == 25.0
    result = simulate_pa_games(inputs, 1000, seed=456)
    assert 0.0 < result.away_win_probability < 1.0
    assert 0.0 < result.home_win_probability < 1.0


def test_live_adapter_prefers_active_roster_reliever_profiles(tmp_path: Path):
    context = _context(tmp_path)
    advanced_path = Path(context.advanced_snapshot_path)
    envelope = __import__("json").loads(advanced_path.read_text(encoding="utf-8"))
    raw_sources = envelope["payload"]["raw_sources"]
    raw_sources["away_bullpen_pitcher_stats"] = {
        "person_ids": [31, 32],
        "reliever_ids": [31, 32],
        "payloads": [_pitching_payload(starts=0, bf=180), _pitching_payload(starts=0, bf=220)],
    }
    raw_sources["home_bullpen_pitcher_stats"] = {
        "person_ids": [41, 42, 43],
        "reliever_ids": [41, 42, 43],
        "payloads": [
            _pitching_payload(starts=0, bf=150),
            _pitching_payload(starts=0, bf=175),
            _pitching_payload(starts=0, bf=200),
        ],
    }
    advanced_path.write_text(__import__("json").dumps(envelope), encoding="utf-8")

    inputs, audit = build_pa_game_inputs_from_context(context)
    assert audit.status == "PARTIAL_PARITY"
    assert audit.reasons == ("BULLPEN_AVAILABILITY_DIAGNOSTIC_ONLY",)
    assert audit.bullpen_profile_source == "active_roster_reliever_season_pitching"
    assert inputs.away_bullpen.opportunities > 0
    assert inputs.home_bullpen.opportunities > 0
    result = simulate_pa_games(inputs, 1000, seed=789)
    assert 0.0 < result.away_win_probability < 1.0
    assert 0.0 < result.home_win_probability < 1.0
