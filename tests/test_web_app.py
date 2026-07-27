from datetime import datetime, timezone

import pytest

from supermodel.odds_input import OddsInputError
from supermodel.providers import PregameContext
from supermodel.web_app import _format_game_time, _is_game_locked, _odds_text_to_number


def test_started_game_is_locked_by_time() -> None:
    context = PregameContext(
        game_date="2026-07-27",
        away_team="NYY",
        home_team="BOS",
        game_datetime="2026-07-27T23:00:00Z",
    )
    assert _is_game_locked(
        context,
        now=datetime(2026, 7, 27, 23, 0, tzinfo=timezone.utc),
    )


def test_preview_game_before_start_is_available() -> None:
    context = PregameContext(
        game_date="2026-07-27",
        away_team="NYY",
        home_team="BOS",
        game_datetime="2026-07-27T23:00:00Z",
        status_abstract="Preview",
    )
    assert not _is_game_locked(
        context,
        now=datetime(2026, 7, 27, 22, 59, tzinfo=timezone.utc),
    )


def test_live_status_locks_game_even_without_time() -> None:
    context = PregameContext(
        game_date="2026-07-27",
        away_team="NYY",
        home_team="BOS",
        status_detailed="In Progress",
    )
    assert _is_game_locked(context)


def test_odds_parser_supports_american_and_decimal() -> None:
    assert _odds_text_to_number("+125", "american") == 125
    assert _odds_text_to_number("-145", "american") == -145
    assert _odds_text_to_number("2.25", "decimal") == 2.25
    assert _odds_text_to_number("", "american") is None


@pytest.mark.parametrize("value", ["99", "-99", "abc"])
def test_invalid_american_odds_fail_closed(value: str) -> None:
    with pytest.raises(OddsInputError):
        _odds_text_to_number(value, "american")


def test_game_time_formatter_handles_missing_values() -> None:
    assert _format_game_time(None) == "Time TBD"


def test_context_table_locks_started_games() -> None:
    from dataclasses import dataclass

    from supermodel.web_app import _context_table

    @dataclass
    class Slate:
        contexts: tuple[PregameContext, ...]

    context = PregameContext(
        game_date="2026-07-27",
        away_team="NYY",
        home_team="BOS",
        game_pk=123,
        game_datetime="2026-07-27T23:00:00Z",
    )
    frame = _context_table(
        Slate((context,)),
        now=datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc),
    )
    assert bool(frame.loc[0, "locked"])
    assert not bool(frame.loc[0, "include"])
