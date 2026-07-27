from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import subprocess
from typing import Iterable

import pandas as pd

from ._version import __version__
from .adaptive_overlay import (
    apply_overlay_to_evaluation,
    fit_adaptive_overlay,
)
from .advanced_features import context_feature_vector
from .evidence import ProspectiveEvidenceLedger
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
from .model_contract import V23_FEATURE_CONTRACT, V24_CANDIDATE_FEATURE_CONTRACT
from .mlb_v2 import (
    attach_official_home_away,
    build_future_features,
    build_pregame_features,
    load_team_logs,
    reconstruct_games,
)
from .market import no_vig_probabilities
from .odds_input import ManualMoneyline
from .providers import PregameContext
from .validation import freeze_v23_feature_contract


@dataclass(frozen=True)
class CapturedSlate:
    """Official point-in-time slate data captured before user odds are entered."""

    game_date: str
    captured_at: datetime
    schedule_path: Path
    pregame_paths: tuple[Path, ...]
    starter_paths: tuple[Path, ...]
    advanced_paths: tuple[Path, ...]
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
    evidence_ledger_path: Path
    adaptive_overlay_path: Path


def _repository_commit() -> str:
    explicit = os.environ.get("SPORTS_SUPERMODEL_GIT_COMMIT")
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


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
    starter_paths = tuple(
        Path(path)
        for context in contexts
        for path in (
            context.away_starter_stats_snapshot_path,
            context.home_starter_stats_snapshot_path,
        )
        if path
    )
    advanced_paths = tuple(
        Path(context.advanced_snapshot_path)
        for context in contexts
        if context.advanced_snapshot_path
    )
    return CapturedSlate(
        game_date=game_date,
        captured_at=timestamp.astimezone(timezone.utc),
        schedule_path=schedule_path,
        pregame_paths=tuple(pregame_paths),
        starter_paths=starter_paths,
        advanced_paths=advanced_paths,
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


def record_prediction_evidence(
    *,
    evaluation: pd.DataFrame,
    contexts: Iterable[PregameContext],
    moneylines: Iterable[ManualMoneyline],
    pregame_paths: Iterable[Path],
    market_snapshot_path: Path,
    prediction_artifact: Path,
    evidence_ledger: str | Path,
    recorded_at: datetime,
    input_source: str,
    starter_paths: Iterable[Path] = (),
    advanced_paths: Iterable[Path] = (),
) -> Path:
    """Append workflow predictions to the hash-chained point-in-time ledger."""

    store = ImmutableSnapshotStore(market_snapshot_path.parent)
    snapshot_path_by_game_pk: dict[int, Path] = {}
    for snapshot_path in pregame_paths:
        envelope = store.read(snapshot_path)
        snapshot_path_by_game_pk[int(envelope["identity"])] = Path(snapshot_path)
    starter_paths_by_game_pk: dict[int, list[Path]] = {}
    for starter_path in starter_paths:
        envelope = store.read(starter_path)
        payload = envelope.get("payload") or {}
        game_pk = int(payload["game_pk"])
        starter_paths_by_game_pk.setdefault(game_pk, []).append(Path(starter_path))
    advanced_path_by_game_pk: dict[int, Path] = {}
    for advanced_path in advanced_paths:
        envelope = store.read(advanced_path)
        payload = envelope.get("payload") or {}
        game_pk = int(payload["game_pk"])
        advanced_path_by_game_pk[game_pk] = Path(advanced_path)
    context_by_game_pk = {
        int(context.game_pk): context
        for context in contexts
        if context.game_pk is not None
    }
    moneyline_list = list(moneylines)
    line_by_game_pk = {
        int(line.game_pk): line for line in moneyline_list if line.game_pk is not None
    }
    ledger_path = Path(evidence_ledger)
    ledger = ProspectiveEvidenceLedger(ledger_path)
    market_snapshot_bytes = market_snapshot_path.read_bytes()

    for row in evaluation.to_dict("records"):
        game_pk = int(row["game_pk"])
        context = context_by_game_pk[game_pk]
        line = line_by_game_pk.get(game_pk)
        if line is None:
            line = next(
                candidate
                for candidate in moneyline_list
                if candidate.game_date == context.game_date
                and candidate.away_team == context.away_team
                and candidate.home_team == context.home_team
            )
        pregame_path = snapshot_path_by_game_pk.get(game_pk)
        if pregame_path is None:
            raise ScheduleIntegrityError(
                f"Missing immutable pregame snapshot for game_pk {game_pk}"
            )
        game_starter_paths = sorted(
            starter_paths_by_game_pk.get(game_pk, []),
            key=lambda path: (
                str((store.read(path).get("payload") or {}).get("side")),
                int((store.read(path).get("payload") or {}).get("pitcher_id", 0)),
            ),
        )
        expected_hashes = {
            side: getattr(context, f"{side}_starter_stats_snapshot_sha256")
            for side in ("away", "home")
            if getattr(context, f"{side}_starter_stats_snapshot_sha256")
        }
        observed_hashes: dict[str, str] = {}
        snapshot_parts = [pregame_path.read_bytes()]
        for starter_path in game_starter_paths:
            envelope = store.read(starter_path)
            side = str((envelope.get("payload") or {}).get("side"))
            digest = sha256(starter_path.read_bytes()).hexdigest()
            observed_hashes[side] = digest
            snapshot_parts.append(starter_path.read_bytes())
        for side, expected_hash in expected_hashes.items():
            if observed_hashes.get(side) != expected_hash:
                raise ScheduleIntegrityError(
                    f"Missing or mismatched {side} starter snapshot for game_pk {game_pk}"
                )
        advanced_path = advanced_path_by_game_pk.get(game_pk)
        if context.advanced_snapshot_sha256:
            if advanced_path is None:
                raise ScheduleIntegrityError(
                    f"Missing immutable advanced context snapshot for game_pk {game_pk}"
                )
            observed_advanced_hash = sha256(advanced_path.read_bytes()).hexdigest()
            if observed_advanced_hash != context.advanced_snapshot_sha256:
                raise ScheduleIntegrityError(
                    f"Advanced context snapshot hash mismatch for game_pk {game_pk}"
                )
            snapshot_parts.append(advanced_path.read_bytes())
        snapshot_parts.append(market_snapshot_bytes)
        combined_snapshot_hash = sha256(b"".join(snapshot_parts)).hexdigest()
        away_implied, home_implied = no_vig_probabilities(
            line.away_odds, line.home_odds
        )
        provenance = dict(context.provenance)
        provenance["market_input"] = input_source
        ledger.append(
            event_type="prediction",
            game_pk=game_pk,
            recorded_at=recorded_at,
            scheduled_start=str(context.game_datetime),
            source="sports_supermodel_workflow",
            snapshot_sha256=combined_snapshot_hash,
            provenance=provenance,
            payload={
                "game_date": context.game_date,
                "away_team": context.away_team,
                "home_team": context.home_team,
                "model_version": __version__,
                "candidate_commit": _repository_commit(),
                "away_probability": float(
                    row.get("shadow_away_probability", row["away_probability"])
                ),
                "home_probability": float(
                    row.get("shadow_home_probability", row["home_probability"])
                ),
                "production_model_version": "2.3.3",
                "production_away_probability": float(row["away_probability"]),
                "production_home_probability": float(row["home_probability"]),
                "base_shadow_away_probability": float(
                    row.get(
                        "shadow_base_shadow_away_probability",
                        row.get("shadow_away_probability", row["away_probability"]),
                    )
                ),
                "base_shadow_home_probability": float(
                    row.get(
                        "shadow_base_shadow_home_probability",
                        row.get("shadow_home_probability", row["home_probability"]),
                    )
                ),
                "offered_away_implied": away_implied,
                "offered_home_implied": home_implied,
                "away_odds": int(line.away_odds),
                "home_odds": int(line.home_odds),
                "model_overlap": int(row.get("shadow_model_overlap", row["model_overlap"])),
                "model_count": int(row["model_count"]),
                "production_model_overlap": int(row["model_overlap"]),
                "adaptive_overlay_status": row.get("shadow_adaptive_overlay_status"),
                "adaptive_overlay_sha256": row.get("shadow_adaptive_overlay_sha256"),
                "context_features_home_orientation": context_feature_vector(context),
                "away_starter_id": context.away_probable_pitcher_id,
                "home_starter_id": context.home_probable_pitcher_id,
                "away_starter_name": context.away_probable_pitcher_name,
                "home_starter_name": context.home_probable_pitcher_name,
                "away_starter_snapshot_sha256": (
                    context.away_starter_stats_snapshot_sha256
                ),
                "home_starter_snapshot_sha256": (
                    context.home_starter_stats_snapshot_sha256
                ),
                "starter_stats_complete": bool(
                    context.away_starter_stats_snapshot_sha256
                    and context.home_starter_stats_snapshot_sha256
                ),
                "advanced_snapshot_sha256": context.advanced_snapshot_sha256,
                "prediction_artifact": str(prediction_artifact),
            },
        )
    return ledger_path


def combine_production_and_shadow(
    production: pd.DataFrame,
    shadow: pd.DataFrame,
) -> pd.DataFrame:
    """Keep V2.3.3 in the primary columns and attach V2.4 as a versioned shadow."""

    if production.empty or shadow.empty:
        raise ValueError("production and shadow evaluations must both be non-empty")
    if set(production["game_pk"].astype(int)) != set(shadow["game_pk"].astype(int)):
        raise ValueError("production and shadow evaluations must contain identical games")
    identity = {
        "game_date",
        "game_pk",
        "away_team",
        "home_team",
        "away_odds",
        "home_odds",
        "model_count",
        "simulations",
    }
    shadow_columns = {
        column: f"shadow_{column}"
        for column in shadow.columns
        if column not in identity
    }
    shadow_view = shadow.rename(columns=shadow_columns)
    keep = [column for column in shadow_view.columns if column == "game_pk" or column.startswith("shadow_")]
    combined = production.merge(shadow_view[keep], on="game_pk", how="inner", validate="one_to_one")
    combined["production_model_version"] = "2.3.3"
    combined["shadow_model_version"] = __version__
    combined["shadow_candidate_commit"] = _repository_commit()
    combined["production_shadow_disagree"] = (
        combined["pick"].astype(str) != combined["shadow_pick"].astype(str)
    )
    combined["shadow_probability_advantage"] = (
        combined["shadow_pick_probability"] - combined["pick_probability"]
    )
    return combined.sort_values(
        ["confidence_rank", "shadow_confidence_rank", "game_pk"]
    ).reset_index(drop=True)


def evaluate_captured_slate(
    *,
    captured_slate: CapturedSlate,
    moneylines: list[ManualMoneyline],
    data_dir: str | Path = "data/2026",
    snapshot_dir: str | Path = "runtime/snapshots",
    output_dir: str | Path = "runtime/reports",
    evidence_ledger: str | Path = "runtime/evidence/prospective.jsonl",
    adaptive_overlay_path: str | Path = "runtime/models/v2_4_adaptive_overlay.json",
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
    candidate_historical_features = build_pregame_features(
        games,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        include_opponent_adjusted_recent_form=(
            V24_CANDIDATE_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
        ),
    )
    production_historical_features = freeze_v23_feature_contract(
        build_pregame_features(
            games,
            recent_form_alpha=V23_FEATURE_CONTRACT.recent_form_alpha,
            include_opponent_adjusted_recent_form=(
                V23_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
            ),
        )
    )
    matchups = contexts_to_matchups(selected_contexts)
    external = pd.DataFrame(
        [context_to_external_feature_record(context) for context in selected_contexts]
    )
    candidate_future_features = build_future_features(
        games,
        matchups,
        external,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        include_opponent_adjusted_recent_form=(
            V24_CANDIDATE_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
        ),
    )

    production_future_features = freeze_v23_feature_contract(
        build_future_features(
            games,
            matchups,
            external,
            recent_form_alpha=V23_FEATURE_CONTRACT.recent_form_alpha,
            include_opponent_adjusted_recent_form=(
                V23_FEATURE_CONTRACT.include_opponent_adjusted_recent_form
            ),
        )
    )

    production_evaluation = evaluate_live_slate(
        historical_features=production_historical_features,
        future_features=production_future_features,
        moneylines=moneylines,
        config=LiveEvaluationConfig(
            simulations=simulations,
            top_n=top_n,
            home_field_logit_adjustment=home_field_logit_adjustment,
        ),
    )
    base_shadow_evaluation = evaluate_live_slate(
        historical_features=candidate_historical_features,
        future_features=candidate_future_features,
        moneylines=moneylines,
        config=LiveEvaluationConfig(
            simulations=simulations,
            top_n=top_n,
            home_field_logit_adjustment=home_field_logit_adjustment,
        ),
    )
    overlay = fit_adaptive_overlay(evidence_ledger, adaptive_overlay_path)
    shadow_evaluation = apply_overlay_to_evaluation(
        base_shadow_evaluation,
        contexts_by_game_pk={int(context.game_pk): context for context in selected_contexts},
        overlay=overlay,
        top_n=top_n,
    )
    evaluation = combine_production_and_shadow(production_evaluation, shadow_evaluation)
    parlays = None
    if include_parlays:
        parlays = evaluate_top_pick_parlays(production_evaluation, simulations=simulations)

    timestamp = market_timestamp.strftime("%Y%m%dT%H%M%SZ")
    csv_path, parlay_path, json_path = write_evaluation_artifacts(
        evaluation,
        output_dir=output_dir,
        stem=f"mlb_v2_4_{captured_slate.game_date}_{timestamp}",
        parlays=parlays,
    )

    ledger_path = record_prediction_evidence(
        evaluation=evaluation,
        contexts=selected_contexts,
        moneylines=moneylines,
        pregame_paths=captured_slate.pregame_paths,
        market_snapshot_path=market_snapshot_path,
        prediction_artifact=json_path,
        evidence_ledger=evidence_ledger,
        recorded_at=market_timestamp,
        input_source=input_source,
        starter_paths=captured_slate.starter_paths,
        advanced_paths=captured_slate.advanced_paths,
    )

    return WorkflowResult(
        evaluation=evaluation,
        parlays=parlays,
        csv_path=csv_path,
        parlay_path=parlay_path,
        json_path=json_path,
        market_snapshot_path=market_snapshot_path,
        evidence_ledger_path=ledger_path,
        adaptive_overlay_path=Path(adaptive_overlay_path),
    )
