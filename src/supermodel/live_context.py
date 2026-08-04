from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable

from .game_registry import ImmutableSnapshotStore
from .live_mlb import MLBStatsHTTPClient, capture_live_slate
from .providers import PregameContext


class ContextStatus(StrEnum):
    PASS = "PASS"
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ContextFreshnessPolicy:
    """Fail-closed timing policy for live baseball context.

    Lineups normally are not posted until close to first pitch, so they are only a
    hard blocker inside ``lineup_required_within``. Starting pitchers are required
    earlier because a missing or changed starter can invalidate a slate run.
    """

    starter_required_within: timedelta = timedelta(hours=8)
    lineup_required_within: timedelta = timedelta(minutes=90)
    weather_required_within: timedelta = timedelta(hours=3)
    max_snapshot_age: timedelta = timedelta(minutes=45)


@dataclass(frozen=True)
class LiveContextAssessment:
    game_pk: int
    away_team: str
    home_team: str
    scheduled_start_utc: str | None
    assessed_at_utc: str
    starter_status: str
    lineup_status: str
    roster_status: str
    weather_status: str
    roof_status: str
    overall_status: str
    block_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]
    probable_pitchers_confirmed: bool
    lineups_confirmed: bool
    away_probable_pitcher_name: str | None
    home_probable_pitcher_name: str | None
    roof_value: str | None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["block_reasons"] = list(self.block_reasons)
        payload["warning_reasons"] = list(self.warning_reasons)
        return payload


@dataclass(frozen=True)
class LiveContextRefreshReport:
    status: str
    slate_date: str
    captured_at_utc: str
    snapshot_path: str
    game_count: int
    blocked_game_pks: tuple[int, ...]
    assessments: tuple[LiveContextAssessment, ...]
    roster_snapshot_paths: tuple[str, ...]
    transaction_snapshot_path: str | None
    provider: str = "mlb_stats_api"

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocked_game_pks"] = list(self.blocked_game_pks)
        payload["assessments"] = [item.to_record() for item in self.assessments]
        payload["roster_snapshot_paths"] = list(self.roster_snapshot_paths)
        return payload


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def assess_live_context(
    context: PregameContext,
    *,
    assessed_at: datetime,
    policy: ContextFreshnessPolicy | None = None,
    roster_loaded: bool = False,
) -> LiveContextAssessment:
    active_policy = policy or ContextFreshnessPolicy()
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ValueError("assessed_at must be timezone-aware")
    now = assessed_at.astimezone(timezone.utc)
    start = _parse_utc(context.game_datetime)
    seconds_to_start = (start - now).total_seconds() if start is not None else None

    block: list[str] = []
    warning: list[str] = []

    if start is None:
        starter_status = ContextStatus.BLOCKED
        lineup_status = ContextStatus.BLOCKED
        weather_status = ContextStatus.BLOCKED
        block.append("MISSING_GAME_TIME")
    else:
        if context.probable_pitchers_confirmed:
            starter_status = ContextStatus.PASS
        elif seconds_to_start is not None and seconds_to_start <= active_policy.starter_required_within.total_seconds():
            starter_status = ContextStatus.BLOCKED
            block.append("STARTER_UNRESOLVED")
        else:
            starter_status = ContextStatus.PENDING
            warning.append("STARTER_NOT_YET_CONFIRMED")

        if context.lineups_confirmed:
            lineup_status = ContextStatus.PASS
        elif seconds_to_start is not None and seconds_to_start <= active_policy.lineup_required_within.total_seconds():
            lineup_status = ContextStatus.BLOCKED
            block.append("LINEUP_UNCONFIRMED_NEAR_FIRST_PITCH")
        else:
            lineup_status = ContextStatus.PENDING
            warning.append("LINEUP_NOT_YET_POSTED")

        weather_present = any(
            value not in (None, "")
            for value in (
                context.temperature_f,
                context.weather_condition,
                context.wind_description,
            )
        )
        if weather_present:
            weather_status = ContextStatus.PASS
        elif seconds_to_start is not None and seconds_to_start <= active_policy.weather_required_within.total_seconds():
            weather_status = ContextStatus.BLOCKED
            block.append("WEATHER_UNAVAILABLE_NEAR_FIRST_PITCH")
        else:
            weather_status = ContextStatus.PENDING
            warning.append("WEATHER_NOT_YET_AVAILABLE")

    roster_status = ContextStatus.PASS if roster_loaded else ContextStatus.PENDING
    if not roster_loaded:
        warning.append("ROSTER_TRANSACTION_FEED_NOT_LOADED")

    roof_text = str(context.roof_status or "").strip()
    if roof_text:
        roof_status = ContextStatus.PASS
    elif context.venue_id is None:
        roof_status = ContextStatus.PENDING
        warning.append("ROOF_STATUS_UNKNOWN")
    else:
        # Outdoor venues commonly have no actionable roof decision. Keep this as a
        # warning rather than a blocker until a venue capability registry is loaded.
        roof_status = ContextStatus.PENDING
        warning.append("ROOF_STATUS_NOT_DECLARED")

    overall = ContextStatus.BLOCKED if block else ContextStatus.PASS
    return LiveContextAssessment(
        game_pk=int(context.game_pk or -1),
        away_team=context.away_team,
        home_team=context.home_team,
        scheduled_start_utc=_utc_text(start) if start is not None else None,
        assessed_at_utc=_utc_text(now),
        starter_status=str(starter_status),
        lineup_status=str(lineup_status),
        roster_status=str(roster_status),
        weather_status=str(weather_status),
        roof_status=str(roof_status),
        overall_status=str(overall),
        block_reasons=tuple(dict.fromkeys(block)),
        warning_reasons=tuple(dict.fromkeys(warning)),
        probable_pitchers_confirmed=bool(context.probable_pitchers_confirmed),
        lineups_confirmed=bool(context.lineups_confirmed),
        away_probable_pitcher_name=context.away_probable_pitcher_name,
        home_probable_pitcher_name=context.home_probable_pitcher_name,
        roof_value=context.roof_status,
    )


def apply_live_context_assessments(
    contexts: Iterable[PregameContext],
    *,
    assessed_at: datetime,
    policy: ContextFreshnessPolicy | None = None,
    roster_team_ids: set[int] | None = None,
) -> tuple[LiveContextAssessment, ...]:
    loaded = roster_team_ids or set()
    return tuple(
        assess_live_context(
            context,
            assessed_at=assessed_at,
            policy=policy,
            roster_loaded=bool(
                context.away_team_id in loaded and context.home_team_id in loaded
            ),
        )
        for context in contexts
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def refresh_live_context(
    *,
    slate_date: str,
    snapshot_dir: str | Path = "runtime/snapshots",
    report_root: str | Path = "runtime/live_context",
    client: MLBStatsHTTPClient | None = None,
    captured_at: datetime | None = None,
    policy: ContextFreshnessPolicy | None = None,
) -> LiveContextRefreshReport:
    """Capture official live context, rosters, and transactions with explicit status.

    Provider failures are never converted into synthetic values. The caller receives
    the original exception and can stop a publish cycle when live context is required.
    """

    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    api_client = client or MLBStatsHTTPClient()
    store = ImmutableSnapshotStore(snapshot_dir)
    _, _, contexts = capture_live_slate(
        game_date=slate_date,
        client=api_client,
        snapshot_store=store,
        captured_at=timestamp,
    )

    root = Path(report_root) / slate_date
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    roster_paths: list[str] = []
    roster_team_ids: set[int] = set()
    for team_id in sorted(
        {
            int(value)
            for context in contexts
            for value in (context.away_team_id, context.home_team_id)
            if value is not None
        }
    ):
        method = getattr(api_client, "team_roster", None)
        if method is None:
            continue
        payload = method(team_id, slate_date)
        roster_path = root / "rosters" / f"{team_id}-{stamp}.json"
        _write_json_atomic(
            roster_path,
            {
                "provider": "mlb_stats_api",
                "captured_at_utc": _utc_text(timestamp),
                "team_id": team_id,
                "payload": payload,
            },
        )
        roster_paths.append(str(roster_path))
        roster_team_ids.add(team_id)

    transaction_path: str | None = None
    method = getattr(api_client, "transactions", None)
    if method is not None:
        start = (datetime.fromisoformat(slate_date).date() - timedelta(days=3)).isoformat()
        payload = method(start, slate_date)
        target = root / f"transactions-{stamp}.json"
        _write_json_atomic(
            target,
            {
                "provider": "mlb_stats_api",
                "captured_at_utc": _utc_text(timestamp),
                "start_date": start,
                "end_date": slate_date,
                "payload": payload,
            },
        )
        transaction_path = str(target)

    assessments = apply_live_context_assessments(
        contexts,
        assessed_at=timestamp,
        policy=policy,
        roster_team_ids=roster_team_ids,
    )
    blocked = tuple(
        item.game_pk for item in assessments if item.overall_status == ContextStatus.BLOCKED
    )
    report_path = root / f"live-context-{stamp}.json"
    report = LiveContextRefreshReport(
        status="BLOCKED" if blocked else "PASS",
        slate_date=slate_date,
        captured_at_utc=_utc_text(timestamp),
        snapshot_path=str(report_path),
        game_count=len(assessments),
        blocked_game_pks=blocked,
        assessments=assessments,
        roster_snapshot_paths=tuple(roster_paths),
        transaction_snapshot_path=transaction_path,
    )
    _write_json_atomic(report_path, report.to_record())
    return report


def apply_live_context_policy(
    evaluation: Any,
    *,
    contexts_by_game_pk: dict[int, PregameContext],
    assessed_at: datetime,
    top_n: int,
    policy: ContextFreshnessPolicy | None = None,
) -> Any:
    """Annotate evaluation rows and fail closed on unresolved critical inputs.

    This is a recommendation gate only. It never changes model probabilities or
    component votes.
    """

    import pandas as pd

    if evaluation.empty:
        return evaluation.copy()
    rows: list[dict[str, Any]] = []
    for row in evaluation.to_dict("records"):
        game_pk = int(row["game_pk"])
        context = contexts_by_game_pk[game_pk]
        assessment = assess_live_context(
            context,
            assessed_at=assessed_at,
            policy=policy,
            roster_loaded=False,
        )
        existing_reasons = [
            value for value in str(row.get("selection_reasons") or "").split(";") if value
        ]
        blocked = bool(assessment.block_reasons)
        reasons = list(dict.fromkeys([*existing_reasons, *assessment.block_reasons]))
        if blocked:
            row["selection_status"] = "BLOCKED — LIVE CONTEXT"
            row["eligible_for_top_pick"] = False
            row["is_top_pick"] = False
        row.update(
            {
                "live_context_status": assessment.overall_status,
                "live_context_block_reasons": ";".join(assessment.block_reasons),
                "live_context_warnings": ";".join(assessment.warning_reasons),
                "starter_status": assessment.starter_status,
                "lineup_status": assessment.lineup_status,
                "roster_status": assessment.roster_status,
                "weather_status": assessment.weather_status,
                "roof_context_status": assessment.roof_status,
                "selection_reasons": ";".join(reasons),
                "selection_reason_count": len(reasons),
            }
        )
        rows.append(row)
    result = pd.DataFrame(rows)
    eligible = result.index[result["eligible_for_top_pick"].fillna(False)].tolist()
    result["selection_rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    for rank, index in enumerate(eligible, start=1):
        result.loc[index, "selection_rank"] = rank
    result["is_top_pick"] = (
        result["eligible_for_top_pick"].fillna(False)
        & result["selection_rank"].notna()
        & (result["selection_rank"] <= int(top_n))
    )
    return result
