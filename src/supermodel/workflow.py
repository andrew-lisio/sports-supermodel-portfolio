from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .game_registry import ImmutableSnapshotStore, ScheduleIntegrityError, parse_mlb_schedule
from .live_mlb import (
    LiveEvaluationConfig,
    MLBStatsHTTPClient,
    capture_live_slate,
    context_to_external_feature_record,
    contexts_to_matchups,
    evaluate_live_slate,
    evaluate_top_pick_parlays,
    write_evaluation_artifacts,
)
from .model_contract import V24_CANDIDATE_FEATURE_CONTRACT
from .mlb_v2 import (
    attach_official_home_away,
    build_future_features,
    build_pregame_features,
    load_team_logs,
    reconstruct_games,
)
from .odds_input import ManualMoneyline
from .providers import PregameContext


@dataclass(frozen=True)
class CapturedSlate:
    """Official point-in-time slate data captured before user odds are entered."""

    game_date: str
    captured_at: datetime
    schedule_path: Path
    pregame_paths: tuple[Path, ...]
    contexts: tuple[PregameContext, ...]


@dataclass(frozen=True)
class WorkflowResult:
    """Complete output from one prediction-only slate evaluation."""

    evaluation: pd.DataFrame
    parlays: pd.DataFrame | None
    csv_path: Path
    parlay_path: Path | None
    json_path: Path
    market_snapshot_path: Path


def capture_official_slate(
    *,
    game_date: str,
    snapshot_dir: str | Path = "runtime/snapshots",
    client: MLBStatsHTTPClient | None = None,
    captured_at: datetime | None = None,
) -> CapturedSlate:
    """Fetch and freeze the official MLB schedule and available pregame context."""

    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    api_client = client or MLBStatsHTTPClient()
    store = ImmutableSnapshotStore(snapshot_dir)
    schedule_path, pregame_paths, contexts = capture_live_slate(
        game_date=game_date,
        client=api_client,
        snapshot_store=store,
        captured_at=timestamp,
    )
    return CapturedSlate(
        game_date=game_date,
        captured_at=timestamp.astimezone(timezone.utc),
        schedule_path=schedule_path,
        pregame_paths=tuple(pregame_paths),
        contexts=tuple(contexts),
    )


def select_contexts_for_moneylines(
    contexts: Iterable[PregameContext],
    moneylines: Iterable[ManualMoneyline],
) -> list[PregameContext]:
    """Match each user line to exactly one official game, preserving input order."""

    context_list = list(contexts)
    by_pk = {context.game_pk: context for context in context_list if context.game_pk is not None}
    selected: list[PregameContext] = []
    used_pks: set[int] = set()

    for line in moneylines:
        context: PregameContext | None = None
        if line.game_pk is not None:
            context = by_pk.get(line.game_pk)
            if context is None:
                raise ValueError(f"game_pk {line.game_pk} was not found on the official slate")
            if (
                context.game_date != line.game_date
                or context.away_team != line.away_team
                or context.home_team != line.home_team
            ):
                raise ValueError(
                    f"game_pk {line.game_pk} does not match "
                    f"{line.away_team} at {line.home_team} on {line.game_date}"
                )
        else:
            candidates = [
                candidate
                for candidate in context_list
                if candidate.game_date == line.game_date
                and candidate.away_team == line.away_team
                and candidate.home_team == line.home_team
            ]
            if not candidates:
                raise ValueError(
                    f"Could not match {line.away_team} at {line.home_team} "
                    f"on {line.game_date} to the official schedule"
                )
            if len(candidates) > 1:
                raise ValueError(
                    f"{line.away_team} at {line.home_team} is a doubleheader or duplicate; "
                    "supply the official game_pk"
                )
            context = candidates[0]

        if context.game_pk is not None and context.game_pk in used_pks:
            raise ValueError(f"Duplicate market input for game_pk {context.game_pk}")
        if context.game_pk is not None:
            used_pks.add(context.game_pk)
        selected.append(context)

    return selected


def _assert_pregame_capture(
    contexts: Iterable[PregameContext],
    captured_at: datetime,
) -> None:
    for context in contexts:
        if not context.game_datetime:
            raise ScheduleIntegrityError(
                f"Official game time is missing for game_pk {context.game_pk}"
            )
        start = datetime.fromisoformat(context.game_datetime.replace("Z", "+00:00"))
        if captured_at > start:
            raise ScheduleIntegrityError(
                f"Context for game_pk {context.game_pk} was captured after its scheduled start"
            )


def evaluate_captured_slate(
    *,
    captured_slate: CapturedSlate,
    moneylines: list[ManualMoneyline],
    data_dir: str | Path = "data/2026",
    snapshot_dir: str | Path = "runtime/snapshots",
    output_dir: str | Path = "runtime/reports",
    simulations: int = 100_000,
    top_n: int = 5,
    home_field_logit_adjustment: float = 0.0,
    include_parlays: bool = True,
    input_source: str = "user_supplied",
    market_captured_at: datetime | None = None,
    client: MLBStatsHTTPClient | None = None,
) -> WorkflowResult:
    """Run the complete prediction-only pipeline from a captured official slate."""

    if not moneylines:
        raise ValueError("At least one complete two-way moneyline is required")
    selected_contexts = select_contexts_for_moneylines(captured_slate.contexts, moneylines)
    _assert_pregame_capture(selected_contexts, captured_slate.captured_at)
    market_timestamp = market_captured_at or datetime.now(timezone.utc)
    if market_timestamp.tzinfo is None or market_timestamp.utcoffset() is None:
        raise ValueError("market_captured_at must be timezone-aware")
    market_timestamp = market_timestamp.astimezone(timezone.utc)
    _assert_pregame_capture(selected_contexts, market_timestamp)

    store = ImmutableSnapshotStore(snapshot_dir)
    market_snapshot_path = store.write(
        kind="market_input",
        captured_at=market_timestamp,
        payload={
            "game_date": captured_slate.game_date,
            "input_source": input_source,
            "moneylines": [asdict(line) for line in moneylines],
        },
        source=input_source,
        identity=captured_slate.game_date,
    )

    api_client = client or MLBStatsHTTPClient()
    logs = load_team_logs(data_dir)
    games = reconstruct_games(logs)
    history_start = pd.to_datetime(games["date"]).min().date().isoformat()
    history_end = (pd.Timestamp(captured_slate.game_date) - pd.Timedelta(days=1)).date().isoformat()
    history_schedule_payload = api_client.schedule_range(history_start, history_end)
    store.write_schedule(
        raw_payload=history_schedule_payload,
        captured_at=market_timestamp,
        source="mlb_stats_api:v1/schedule:historical_identity_backfill",
    )
    games = attach_official_home_away(games, parse_mlb_schedule(history_schedule_payload))
    historical_features = build_pregame_features(
        games,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        include_opponent_adjusted_recent_form=(
            V24_CANDIDATE_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
        ),
    )
    matchups = contexts_to_matchups(selected_contexts)
    external = pd.DataFrame(
        [context_to_external_feature_record(context) for context in selected_contexts]
    )
    future_features = build_future_features(
        games,
        matchups,
        external,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        include_opponent_adjusted_recent_form=(
            V24_CANDIDATE_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
        ),
    )

    evaluation = evaluate_live_slate(
        historical_features=historical_features,
        future_features=future_features,
        moneylines=moneylines,
        config=LiveEvaluationConfig(
            simulations=simulations,
            top_n=top_n,
            home_field_logit_adjustment=home_field_logit_adjustment,
        ),
    )
    parlays = None
    if include_parlays:
        parlays = evaluate_top_pick_parlays(evaluation, simulations=simulations)

    timestamp = market_timestamp.strftime("%Y%m%dT%H%M%SZ")
    csv_path, parlay_path, json_path = write_evaluation_artifacts(
        evaluation,
        output_dir=output_dir,
        stem=f"mlb_v2_3_2_{captured_slate.game_date}_{timestamp}",
        parlays=parlays,
    )
    return WorkflowResult(
        evaluation=evaluation,
        parlays=parlays,
        csv_path=csv_path,
        parlay_path=parlay_path,
        json_path=json_path,
        market_snapshot_path=market_snapshot_path,
    )
