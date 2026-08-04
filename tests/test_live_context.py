from datetime import datetime, timedelta, timezone
from pathlib import Path

from supermodel.live_context import (
    ContextFreshnessPolicy,
    LiveContextAssessment,
    LiveContextRefreshReport,
    assess_live_context,
    live_context_game_fingerprints,
)
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

def test_precomputed_assessment_preserves_loaded_roster_status():
    import pandas as pd

    from supermodel.live_context import apply_live_context_policy

    now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    item = context(now + timedelta(hours=4))
    assessment = LiveContextAssessment(
        game_pk=123,
        away_team="Away",
        home_team="Home",
        scheduled_start_utc=item.game_datetime,
        assessed_at_utc=now.isoformat().replace("+00:00", "Z"),
        starter_status="PASS",
        lineup_status="PENDING",
        roster_status="PASS",
        weather_status="PENDING",
        roof_status="PENDING",
        overall_status="PASS",
        block_reasons=(),
        warning_reasons=("LINEUP_NOT_YET_POSTED",),
        probable_pitchers_confirmed=True,
        lineups_confirmed=False,
        away_probable_pitcher_name=None,
        home_probable_pitcher_name=None,
        roof_value=None,
    )
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
        assessments_by_game_pk={123: assessment},
    )
    assert result.loc[0, "roster_status"] == "PASS"
    assert "ROSTER_TRANSACTION_FEED_NOT_LOADED" not in result.loc[0, "live_context_warnings"]


def test_live_context_fingerprint_is_stable_and_game_specific(tmp_path):
    import json

    first = context(datetime(2026, 8, 4, 19, tzinfo=timezone.utc))
    first.away_team_id = 1
    first.home_team_id = 2
    second = PregameContext(
        game_date="2026-08-04",
        game_pk=456,
        away_team="Other Away",
        home_team="Other Home",
        game_datetime="2026-08-04T20:00:00Z",
        away_team_id=3,
        home_team_id=4,
        probable_pitchers_confirmed=True,
    )

    roster_paths = []
    for team_id in (1, 2, 3, 4):
        path = tmp_path / f"{team_id}.json"
        path.write_text(
            json.dumps(
                {
                    "provider": "mlb_stats_api",
                    "captured_at_utc": "2026-08-04T12:00:00Z",
                    "team_id": team_id,
                    "payload": {"roster": [{"person": {"id": team_id * 10}}]},
                }
            ),
            encoding="utf-8",
        )
        roster_paths.append(str(path))

    transaction_path = tmp_path / "transactions.json"
    transaction_path.write_text(
        json.dumps(
            {
                "captured_at_utc": "2026-08-04T12:00:00Z",
                "payload": {
                    "transactions": [
                        {"id": 1, "effectiveDate": "2026-08-04", "toTeam": {"id": 1}}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    def assessment(game_pk, away, home):
        return LiveContextAssessment(
            game_pk=game_pk,
            away_team=away,
            home_team=home,
            scheduled_start_utc="2026-08-04T19:00:00Z",
            assessed_at_utc="2026-08-04T12:00:00Z",
            starter_status="PASS",
            lineup_status="PENDING",
            roster_status="PASS",
            weather_status="PENDING",
            roof_status="PENDING",
            overall_status="PASS",
            block_reasons=(),
            warning_reasons=("LINEUP_NOT_YET_POSTED",),
            probable_pitchers_confirmed=True,
            lineups_confirmed=False,
            away_probable_pitcher_name=None,
            home_probable_pitcher_name=None,
            roof_value=None,
        )

    report = LiveContextRefreshReport(
        status="PASS",
        slate_date="2026-08-04",
        captured_at_utc="2026-08-04T12:00:00Z",
        snapshot_path=str(tmp_path / "live.json"),
        game_count=2,
        blocked_game_pks=(),
        assessments=(
            assessment(123, "Away", "Home"),
            assessment(456, "Other Away", "Other Home"),
        ),
        roster_snapshot_paths=tuple(roster_paths),
        transaction_snapshot_path=str(transaction_path),
    )
    contexts = {123: first, 456: second}
    original = live_context_game_fingerprints(report, contexts_by_game_pk=contexts)

    document = json.loads(Path(roster_paths[0]).read_text(encoding="utf-8"))
    document["captured_at_utc"] = "2026-08-04T12:05:00Z"
    Path(roster_paths[0]).write_text(json.dumps(document), encoding="utf-8")
    timestamp_only = live_context_game_fingerprints(report, contexts_by_game_pk=contexts)
    assert timestamp_only == original

    document["payload"]["roster"].append({"person": {"id": 999}})
    Path(roster_paths[0]).write_text(json.dumps(document), encoding="utf-8")
    changed = live_context_game_fingerprints(report, contexts_by_game_pk=contexts)
    assert changed[123] != original[123]
    assert changed[456] == original[456]
