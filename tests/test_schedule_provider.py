from __future__ import annotations

from pathlib import Path

import pytest

from supermodel.game_registry import ImmutableSnapshotStore
from supermodel.providers import OfficialScheduleSnapshotProvider, PregameContext


def _payload() -> dict:
    games = []
    for game_pk, game_number, game_date in [
        (910001, 1, "2026-07-19T17:05:00Z"),
        (910002, 2, "2026-07-19T23:05:00Z"),
    ]:
        games.append({
            "gamePk": game_pk,
            "gameDate": game_date,
            "gameNumber": game_number,
            "doubleHeader": "Y",
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
            "venue": {"id": 3313, "name": "Example Stadium"},
            "teams": {
                "away": {
                    "team": {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD"},
                    "probablePitcher": {"id": 7001, "fullName": "LAD Starter"},
                },
                "home": {
                    "team": {"id": 147, "name": "New York Yankees", "abbreviation": "NYY"},
                    "probablePitcher": {"id": 7002, "fullName": "NYY Starter"},
                },
            },
        })
    return {"dates": [{"date": "2026-07-19", "games": games}]}


def _snapshot(tmp_path: Path) -> Path:
    return ImmutableSnapshotStore(tmp_path).write_schedule(
        raw_payload=_payload(),
        captured_at="2026-07-19T10:00:00-04:00",
        source="official-test-fixture",
    )


def test_provider_enriches_exact_game_pk(tmp_path: Path):
    provider = OfficialScheduleSnapshotProvider(_snapshot(tmp_path))
    context = PregameContext(
        game_date="2026-07-19",
        away_team="LAD",
        home_team="NYY",
        game_pk=910002,
    )
    enriched = provider.enrich(context)
    assert enriched.game_number == 2
    assert enriched.game_datetime == "2026-07-19T23:05:00Z"
    assert enriched.venue_name == "Example Stadium"
    assert enriched.probable_pitchers_confirmed is True


def test_provider_requires_game_pk_for_ambiguous_doubleheader(tmp_path: Path):
    provider = OfficialScheduleSnapshotProvider(_snapshot(tmp_path))
    context = PregameContext(
        game_date="2026-07-19",
        away_team="LAD",
        home_team="NYY",
    )
    with pytest.raises(ValueError, match="game_pk is required"):
        provider.enrich(context)
