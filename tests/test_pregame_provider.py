from pathlib import Path

import pytest

from supermodel.game_registry import ImmutableSnapshotStore
from supermodel.providers import JsonSnapshotProvider, PregameContext


def _snapshot(tmp_path: Path) -> Path:
    return ImmutableSnapshotStore(tmp_path).write_pregame(
        game_pk=920001,
        game_datetime="2026-07-20T23:05:00Z",
        context_payload={
            "game_date": "2026-07-20",
            "away_team": "LAD",
            "home_team": "PHI",
            "lineups_confirmed": True,
            "home_current_implied": 0.57,
        },
        captured_at="2026-07-20T20:00:00Z",
        source="manual-slate",
    )


def test_pregame_provider_loads_immutable_snapshot_by_game_pk(tmp_path: Path):
    provider = JsonSnapshotProvider(_snapshot(tmp_path))
    context = PregameContext(
        game_date="2026-07-20",
        away_team="LAD",
        home_team="PHI",
        game_pk=920001,
    )
    result = provider.enrich(context)
    assert result.lineups_confirmed is True
    assert result.home_current_implied == pytest.approx(0.57)
    assert result.game_datetime == "2026-07-20T23:05:00Z"


def test_pregame_provider_rejects_wrong_game_pk(tmp_path: Path):
    provider = JsonSnapshotProvider(_snapshot(tmp_path))
    context = PregameContext(
        game_date="2026-07-20",
        away_team="LAD",
        home_team="PHI",
        game_pk=920002,
    )
    with pytest.raises(ValueError, match="does not match"):
        provider.enrich(context)
