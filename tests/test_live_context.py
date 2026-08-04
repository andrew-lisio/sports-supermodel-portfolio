from datetime import datetime, timedelta, timezone

from supermodel.live_context import ContextFreshnessPolicy, assess_live_context
from supermodel.providers import PregameContext


def context(start: datetime) -> PregameContext:
    return PregameContext(
        game_date=start.date().isoformat(),
        game_pk=123,
        away_team="Away",
        home_team="Home",
        game_datetime=start.isoformat().replace("+00:00", "Z"),
        away_probable_pitcher_id=1,
        home_probable_pitcher_id=2,
        probable_pitchers_confirmed=True,
    )


def test_lineup_is_pending_early_and_blocked_near_first_pitch():
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    early = assess_live_context(context(now + timedelta(hours=5)), assessed_at=now)
    assert early.lineup_status == "PENDING"
    assert early.overall_status == "PASS"

    near = assess_live_context(context(now + timedelta(minutes=45)), assessed_at=now)
    assert near.lineup_status == "BLOCKED"
    assert near.overall_status == "BLOCKED"
    assert "LINEUP_UNCONFIRMED_NEAR_FIRST_PITCH" in near.block_reasons


def test_confirmed_context_passes_critical_checks():
    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    item = context(now + timedelta(minutes=30))
    item.lineups_confirmed = True
    item.temperature_f = 78
    item.weather_condition = "Clear"
    assessment = assess_live_context(
        item,
        assessed_at=now,
        policy=ContextFreshnessPolicy(),
        roster_loaded=True,
    )
    assert assessment.overall_status == "PASS"
    assert assessment.starter_status == "PASS"
    assert assessment.lineup_status == "PASS"
    assert assessment.weather_status == "PASS"
    assert assessment.roster_status == "PASS"


def test_live_context_policy_blocks_without_changing_probability():
    import pandas as pd

    from supermodel.live_context import apply_live_context_policy

    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    item = context(now + timedelta(minutes=30))
    frame = pd.DataFrame(
        [
            {
                "game_pk": 123,
                "pick_probability": 0.61,
                "away_probability": 0.39,
                "home_probability": 0.61,
                "selection_status": "ELIGIBLE",
                "selection_reasons": "",
                "eligible_for_top_pick": True,
                "is_top_pick": True,
            }
        ]
    )
    result = apply_live_context_policy(
        frame,
        contexts_by_game_pk={123: item},
        assessed_at=now,
        top_n=5,
    )
    assert result.loc[0, "home_probability"] == 0.61
    assert result.loc[0, "selection_status"] == "BLOCKED — LIVE CONTEXT"
    assert not bool(result.loc[0, "eligible_for_top_pick"])
