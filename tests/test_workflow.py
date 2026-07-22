from __future__ import annotations

import pytest

from supermodel.odds_input import ManualMoneyline
from supermodel.providers import PregameContext
from supermodel.workflow import select_contexts_for_moneylines


def _context(game_pk: int, game_number: int) -> PregameContext:
    return PregameContext(
        game_date="2030-07-20",
        away_team="AAA",
        home_team="BBB",
        game_pk=game_pk,
        game_number=game_number,
        game_datetime=f"2030-07-20T{18 + game_number:02d}:00:00Z",
    )


def test_workflow_uses_game_pk_to_keep_doubleheaders_separate():
    contexts = [_context(101, 1), _context(102, 2)]
    line = ManualMoneyline("2030-07-20", "AAA", "BBB", 120, -130, 102)
    selected = select_contexts_for_moneylines(contexts, [line])
    assert selected[0].game_pk == 102


def test_workflow_rejects_ambiguous_doubleheader_without_game_pk():
    contexts = [_context(101, 1), _context(102, 2)]
    line = ManualMoneyline("2030-07-20", "AAA", "BBB", 120, -130, None)
    with pytest.raises(ValueError, match="doubleheader"):
        select_contexts_for_moneylines(contexts, [line])


def test_workflow_rejects_team_mismatch_for_game_pk():
    contexts = [_context(101, 1)]
    line = ManualMoneyline("2030-07-20", "CCC", "BBB", 120, -130, 101)
    with pytest.raises(ValueError, match="does not match"):
        select_contexts_for_moneylines(contexts, [line])
