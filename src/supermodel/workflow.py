from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import subprocess
from typing import Any, Iterable, Mapping

import yaml

import pandas as pd

from ._version import __version__
from .adaptive_overlay import (
    apply_overlay_to_evaluation,
    fit_adaptive_overlay,
)
from .advanced_features import context_feature_vector
from .evidence import ProspectiveEvidenceLedger
from .game_registry import ImmutableSnapshotStore, ScheduleIntegrityError, parse_mlb_schedule
from .history_refresh import HistoryRefreshReport, refresh_completed_history
from .live_context import LiveContextAssessment, apply_live_context_policy
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
    RANDOM_SEED,
    attach_official_home_away,
    build_future_features,
    build_pregame_features,
    load_team_logs,
    reconstruct_games,
)
from .market import no_vig_probabilities
from .market_schema import MarketQuote, QuoteSource
from .odds_input import ManualMoneyline
from .pa_live import PA_DEFAULT_MONEYLINE_WEIGHT, evaluate_pa_shadow_slate
from .pa_simulator import PA_SIMULATOR_VERSION
from .providers import PregameContext
from .series_context import apply_series_context_policy, build_series_contexts
from .simulation_store import SimulationSnapshot
from .storage import create_market_quote_store, create_simulation_snapshot_store
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
    history_refresh_report: HistoryRefreshReport
    market_quote_path: str | Path | None
    simulation_manifest_paths: tuple[str | Path, ...]
    pa_shadow_evaluation: pd.DataFrame | None = None
    pa_shadow_csv_path: Path | None = None
    pa_shadow_json_path: Path | None = None
    pa_shadow_simulation_manifest_paths: tuple[str | Path, ...] = ()


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


def _candidate_model_commit() -> str:
    """Return the frozen predictive-code commit independently of UI-only commits."""

    explicit = os.environ.get("SPORTS_SUPERMODEL_MODEL_COMMIT")
    if explicit:
        return explicit
    config_path = Path("config/final_candidate.yaml")
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        configured = (payload.get("candidate") or {}).get("model_commit")
        if configured:
            return str(configured)
    except (OSError, TypeError, yaml.YAMLError):
        pass
    return _repository_commit()


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
                "candidate_commit": _candidate_model_commit(),
                "repository_commit": _repository_commit(),
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
                "history_freshness_status": row.get("history_freshness_status"),
                "history_checked_through": row.get("history_checked_through"),
                "history_latest_completed_date": row.get("history_latest_completed_date"),
                "history_backfilled_games": int(row.get("history_backfilled_games", 0)),
                "series_context_version": row.get("series_context_version"),
                "series_context_probability_authority": row.get(
                    "series_context_probability_authority"
                ),
                "series_context_status": row.get("series_context_status"),
                "live_context_status": row.get("live_context_status"),
                "live_context_block_reasons": row.get("live_context_block_reasons"),
                "live_context_warnings": row.get("live_context_warnings"),
                "series_context_summary": row.get("series_context_summary"),
                "series_games_played": int(row.get("series_games_played", 0)),
                "series_away_wins": int(row.get("series_away_wins", 0)),
                "series_home_wins": int(row.get("series_home_wins", 0)),
                "series_away_runs": int(row.get("series_away_runs", 0)),
                "series_home_runs": int(row.get("series_home_runs", 0)),
                "series_run_differential_away": int(
                    row.get("series_run_differential_away", 0)
                ),
                "series_previous_results": row.get("series_previous_results"),
                "production_series_context_conflict": bool(
                    row.get("series_context_conflict", False)
                ),
                "production_series_context_reasons": row.get("series_context_reasons"),
                "production_series_context_pick_high_leverage_pitches_yesterday": row.get(
                    "series_context_pick_high_leverage_pitches_yesterday"
                ),
                "production_series_context_pick_closer_available": row.get(
                    "series_context_pick_closer_available"
                ),
                "shadow_series_context_conflict": bool(
                    row.get("shadow_series_context_conflict", False)
                ),
                "shadow_series_context_reasons": row.get(
                    "shadow_series_context_reasons"
                ),
                "selection_policy_version": row.get(
                    "shadow_selection_policy_version", row.get("selection_policy_version")
                ),
                "selection_policy_mode": row.get(
                    "shadow_selection_policy_mode", row.get("selection_policy_mode")
                ),
                "production_raw_pick": row.get("pick"),
                "production_selection_status": row.get("selection_status"),
                "production_selection_reasons": row.get("selection_reasons"),
                "production_component_consensus_pick": row.get("component_consensus_pick"),
                "production_projected_score_pick": row.get("projected_score_pick"),
                "shadow_raw_pick": row.get("shadow_pick", row.get("pick")),
                "shadow_selection_status": row.get(
                    "shadow_selection_status", row.get("selection_status")
                ),
                "shadow_selection_reasons": row.get(
                    "shadow_selection_reasons", row.get("selection_reasons")
                ),
                "shadow_component_consensus_pick": row.get(
                    "shadow_component_consensus_pick", row.get("component_consensus_pick")
                ),
                "shadow_projected_score_pick": row.get(
                    "shadow_projected_score_pick", row.get("projected_score_pick")
                ),
                "selection_status": row.get(
                    "shadow_selection_status", row.get("selection_status")
                ),
                "selection_reasons": row.get(
                    "shadow_selection_reasons", row.get("selection_reasons")
                ),
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
    combined["shadow_candidate_commit"] = _candidate_model_commit()
    combined["shadow_repository_commit"] = _repository_commit()
    combined["production_shadow_disagree"] = (
        combined["pick"].astype(str) != combined["shadow_pick"].astype(str)
    )
    combined["shadow_probability_advantage"] = (
        combined["shadow_pick_probability"] - combined["pick_probability"]
    )
    return combined.sort_values(
        ["confidence_rank", "shadow_confidence_rank", "game_pk"]
    ).reset_index(drop=True)


def _game_input_snapshot_hash(
    *,
    captured_slate: CapturedSlate,
    game_pk: int,
    market_snapshot_path: Path | None = None,
    base_input_hash: str | None = None,
) -> str:
    """Hash immutable inputs used for one canonical simulation snapshot.

    Interactive/manual runs keep the captured market payload in the identity for
    backward compatibility. Scheduled backend publications pass a baseball-only
    ``base_input_hash`` and omit the market path so changing odds only reprices an
    existing distribution instead of forcing another simulation.
    """

    parts = [captured_slate.schedule_path.read_bytes()]
    if market_snapshot_path is not None:
        parts.append(Path(market_snapshot_path).read_bytes())
    if base_input_hash:
        parts.append(str(base_input_hash).encode("utf-8"))
    candidate_paths = (
        *captured_slate.pregame_paths,
        *captured_slate.starter_paths,
        *captured_slate.advanced_paths,
    )
    for path in sorted(candidate_paths, key=lambda item: str(item)):
        envelope = ImmutableSnapshotStore.read(path)
        payload = envelope.get("payload") or {}
        identity = envelope.get("identity")
        path_game_pk = payload.get("game_pk", identity)
        try:
            matches = int(path_game_pk) == int(game_pk)
        except (TypeError, ValueError):
            matches = False
        if matches:
            parts.append(Path(path).read_bytes())
    return sha256(b"".join(parts)).hexdigest()


def _persist_platform_outputs(
    *,
    captured_slate: CapturedSlate,
    evaluation: pd.DataFrame,
    moneylines: list[ManualMoneyline],
    market_timestamp: datetime,
    market_snapshot_path: Path,
    production_draws: dict[int, tuple[object, object]],
    shadow_draws: dict[int, tuple[object, object]],
    sportsbook_name: str,
    market_store_root: str | Path,
    simulation_store_root: str | Path,
    persist_market_quotes: bool = True,
    snapshot_input_hashes: Mapping[int, str] | None = None,
    snapshot_metadata: Mapping[str, Any] | None = None,
) -> tuple[str | Path | None, tuple[str | Path, ...]]:
    context_by_pk = {
        int(context.game_pk): context
        for context in captured_slate.contexts
        if context.game_pk is not None
    }
    quote_path: str | Path | None = None
    if persist_market_quotes:
        quote_store = create_market_quote_store(market_store_root)
        quotes: list[MarketQuote] = []
        for line in moneylines:
            context = None
            if line.game_pk is not None:
                context = context_by_pk.get(int(line.game_pk))
            if context is None:
                context = next(
                    candidate
                    for candidate in captured_slate.contexts
                    if candidate.game_date == line.game_date
                    and candidate.away_team == line.away_team
                    and candidate.home_team == line.home_team
                )
            game_pk = int(context.game_pk)
            for team, odds in (
                (context.away_team, line.away_odds),
                (context.home_team, line.home_odds),
            ):
                quotes.append(
                    MarketQuote(
                        game_pk=game_pk,
                        sportsbook=sportsbook_name,
                        market_type="moneyline",
                        selection=team,
                        american_odds=int(odds),
                        captured_at=market_timestamp,
                        source=QuoteSource.MANUAL,
                        event_date=captured_slate.game_date,
                    )
                )
        quote_path = quote_store.save_many(quotes)

    snapshot_store = create_simulation_snapshot_store(simulation_store_root)
    manifests: list[str | Path] = []
    extra_metadata = dict(snapshot_metadata or {})
    for row in evaluation.to_dict("records"):
        game_pk = int(row["game_pk"])
        if snapshot_input_hashes is not None and game_pk in snapshot_input_hashes:
            input_hash = str(snapshot_input_hashes[game_pk])
        else:
            input_hash = _game_input_snapshot_hash(
                captured_slate=captured_slate,
                game_pk=game_pk,
                market_snapshot_path=market_snapshot_path,
            )
        away = str(row["away_team"])
        production_components = {
            name: float(row[f"p_{name}_{away}"])
            for name in (
                "logistic",
                "random_forest",
                "neural_network",
                "elo_pyth",
                "xgboost",
                "lightgbm",
                "catboost",
            )
            if f"p_{name}_{away}" in row
        }
        shadow_components = {
            name: float(row[f"shadow_p_{name}_{away}"])
            for name in (
                "logistic",
                "random_forest",
                "neural_network",
                "elo_pyth",
                "xgboost",
                "lightgbm",
                "catboost",
            )
            if f"shadow_p_{name}_{away}" in row
        }
        common_metadata = {
            "game_date": captured_slate.game_date,
            "sportsbook": sportsbook_name if persist_market_quotes else None,
            "odds_available": bool(persist_market_quotes),
            "history_freshness_status": row.get("history_freshness_status"),
            "history_checked_through": row.get("history_checked_through"),
            "lineups_confirmed": bool(row.get("lineups_confirmed", False)),
            "live_context_status": row.get("live_context_status"),
            "live_context_block_reasons": row.get("live_context_block_reasons"),
            "live_context_warnings": row.get("live_context_warnings"),
            "starter_status": row.get("starter_status"),
            "lineup_status": row.get("lineup_status"),
            "roster_status": row.get("roster_status"),
            "weather_status": row.get("weather_status"),
            "roof_context_status": row.get("roof_context_status"),
            "series_context_version": row.get("series_context_version"),
            "series_context_probability_authority": row.get(
                "series_context_probability_authority"
            ),
            "series_context_status": row.get("series_context_status"),
            "series_context_summary": row.get("series_context_summary"),
            "series_games_played": int(row.get("series_games_played", 0)),
            "series_away_wins": int(row.get("series_away_wins", 0)),
            "series_home_wins": int(row.get("series_home_wins", 0)),
            "series_away_runs": int(row.get("series_away_runs", 0)),
            "series_home_runs": int(row.get("series_home_runs", 0)),
            "series_run_differential_away": int(
                row.get("series_run_differential_away", 0)
            ),
            "series_previous_results": row.get("series_previous_results"),
            "series_context_pick_high_leverage_pitches_yesterday": row.get(
                "series_context_pick_high_leverage_pitches_yesterday"
            ),
            "series_context_pick_closer_available": row.get(
                "series_context_pick_closer_available"
            ),
            "series_context_pick_reliever_appearances_weighted": row.get(
                "series_context_pick_reliever_appearances_weighted"
            ),
            **extra_metadata,
        }
        for (
            track,
            draws,
            version,
            commit,
            away_probability,
            home_probability,
            components,
            status,
            reasons,
        ) in (
            (
                "production",
                production_draws,
                "2.3.3",
                _repository_commit(),
                float(row["away_probability"]),
                float(row["home_probability"]),
                production_components,
                row.get("selection_status"),
                row.get("selection_reasons"),
            ),
            (
                "shadow",
                shadow_draws,
                __version__,
                _candidate_model_commit(),
                float(row.get("shadow_away_probability", row["away_probability"])),
                float(row.get("shadow_home_probability", row["home_probability"])),
                shadow_components,
                row.get("shadow_selection_status", row.get("selection_status")),
                row.get("shadow_selection_reasons", row.get("selection_reasons")),
            ),
        ):
            if game_pk not in draws:
                raise ScheduleIntegrityError(
                    f"Missing {track} simulation draws for game_pk {game_pk}"
                )
            away_runs, home_runs = draws[game_pk]
            snapshot = SimulationSnapshot(
                game_pk=game_pk,
                away_team=row["away_team"],
                home_team=row["home_team"],
                model_track=track,
                model_version=version,
                git_commit=commit,
                input_snapshot_hash=input_hash,
                created_at=market_timestamp,
                random_seed=RANDOM_SEED,
                away_runs=away_runs,
                home_runs=home_runs,
                away_win_probability=away_probability,
                home_win_probability=home_probability,
                component_probabilities=components,
                metadata={
                    **common_metadata,
                    "selection_status": status,
                    "selection_reasons": reasons,
                    "series_context_conflict": bool(
                        row.get(
                            "shadow_series_context_conflict"
                            if track == "shadow"
                            else "series_context_conflict",
                            False,
                        )
                    ),
                    "series_context_reasons": row.get(
                        "shadow_series_context_reasons"
                        if track == "shadow"
                        else "series_context_reasons"
                    ),
                    "conflict": str(status).upper().startswith("PASS"),
                    "fresh": row.get("history_freshness_status") == "PASS",
                },
            )
            manifest_path, _ = snapshot_store.save(snapshot)
            manifests.append(manifest_path)
    return quote_path, tuple(manifests)


def _persist_pa_shadow_outputs(
    *,
    captured_slate: CapturedSlate,
    evaluation: pd.DataFrame,
    draws: Mapping[int, tuple[object, object]],
    market_timestamp: datetime,
    market_snapshot_path: Path,
    simulation_store_root: str | Path,
    snapshot_input_hashes: Mapping[int, str] | None = None,
) -> tuple[str | Path, ...]:
    """Persist the PA implementation candidate as a distinct non-authoritative track."""

    if evaluation is None or evaluation.empty:
        return ()
    store = create_simulation_snapshot_store(simulation_store_root)
    manifests: list[str | Path] = []
    for row in evaluation.to_dict("records"):
        if str(row.get("pa_shadow_status")) != "READY":
            continue
        game_pk = int(row["game_pk"])
        if game_pk not in draws:
            raise ScheduleIntegrityError(
                f"Missing pa_shadow simulation draws for game_pk {game_pk}"
            )
        if snapshot_input_hashes is not None and game_pk in snapshot_input_hashes:
            input_hash = str(snapshot_input_hashes[game_pk])
        else:
            input_hash = _game_input_snapshot_hash(
                captured_slate=captured_slate,
                game_pk=game_pk,
                market_snapshot_path=market_snapshot_path,
            )
        away = str(row["away_team"])
        components = {
            name: float(row[f"p_{name}_{away}"])
            for name in (
                "logistic",
                "random_forest",
                "neural_network",
                "elo_pyth",
                "xgboost",
                "lightgbm",
                "catboost",
            )
            if f"p_{name}_{away}" in row
        }
        away_runs, home_runs = draws[game_pk]
        snapshot = SimulationSnapshot(
            game_pk=game_pk,
            away_team=away,
            home_team=str(row["home_team"]),
            model_track="pa_shadow",
            model_version=PA_SIMULATOR_VERSION,
            git_commit=_repository_commit(),
            input_snapshot_hash=input_hash,
            created_at=market_timestamp,
            random_seed=RANDOM_SEED + game_pk,
            away_runs=away_runs,
            home_runs=home_runs,
            away_win_probability=float(row["away_probability"]),
            home_win_probability=float(row["home_probability"]),
            component_probabilities=components,
            metadata={
                "game_date": captured_slate.game_date,
                "production_authority": False,
                "candidate_type": "pa_generative_implementation_shadow",
                "pa_moneyline_weight": float(row["pa_moneyline_weight"]),
                "pa_live_parity_status": row.get("pa_live_parity_status"),
                "pa_live_parity_reasons": row.get("pa_live_parity_reasons"),
                "lineups_confirmed": bool(row.get("lineups_confirmed", False)),
                "score_disagreement_diagnostic": bool(
                    row.get("pa_score_disagreement", False)
                ),
                "score_disagreement_has_veto_authority": False,
            },
        )
        manifest_path, _ = store.save(snapshot)
        manifests.append(manifest_path)
    return tuple(manifests)


def evaluate_captured_slate(
    *,
    captured_slate: CapturedSlate,
    moneylines: list[ManualMoneyline],
    data_dir: str | Path = "data/2026",
    snapshot_dir: str | Path = "runtime/snapshots",
    output_dir: str | Path = "runtime/reports",
    evidence_ledger: str | Path = "runtime/evidence/prospective.jsonl",
    adaptive_overlay_path: str | Path = "runtime/models/v2_4_adaptive_overlay.json",
    history_cache_path: str | Path = "runtime/data/mlb_completed_games.csv",
    simulations: int = 100_000,
    top_n: int = 5,
    home_field_logit_adjustment: float = 0.0,
    include_parlays: bool = True,
    input_source: str = "user_supplied",
    market_captured_at: datetime | None = None,
    client: MLBStatsHTTPClient | None = None,
    sportsbook_name: str = "Custom",
    market_store_root: str | Path = "runtime/markets",
    simulation_store_root: str | Path = "runtime/simulations",
    persist_market_quotes: bool = True,
    record_evidence: bool = True,
    snapshot_input_hashes: Mapping[int, str] | None = None,
    snapshot_metadata: Mapping[str, Any] | None = None,
    live_context_assessments: Mapping[int, LiveContextAssessment] | None = None,
    enable_pa_shadow: bool = False,
    pa_shadow_moneyline_weight: float = PA_DEFAULT_MONEYLINE_WEIGHT,
    pa_shadow_simulations: int | None = None,
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
    base_history_end = pd.to_datetime(games["date"]).max().date().isoformat()
    history_schedule_payload = api_client.schedule_range(history_start, base_history_end)
    store.write_schedule(
        raw_payload=history_schedule_payload,
        captured_at=market_timestamp,
        source="mlb_stats_api:v1/schedule:historical_identity_backfill",
    )
    games = attach_official_home_away(games, parse_mlb_schedule(history_schedule_payload))
    games, history_refresh_report = refresh_completed_history(
        games,
        slate_date=captured_slate.game_date,
        client=api_client,
        snapshot_store=store,
        captured_at=market_timestamp,
        cache_path=history_cache_path,
    )
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

    production_draws: dict[int, tuple[object, object]] = {}
    shadow_draws: dict[int, tuple[object, object]] = {}
    production_evaluation = evaluate_live_slate(
        historical_features=production_historical_features,
        future_features=production_future_features,
        moneylines=moneylines,
        config=LiveEvaluationConfig(
            simulations=simulations,
            top_n=top_n,
            home_field_logit_adjustment=home_field_logit_adjustment,
        ),
        simulation_draws=production_draws,
    )
    series_contexts = build_series_contexts(games, selected_contexts)
    pregame_contexts_by_pk = {
        int(context.game_pk): context
        for context in selected_contexts
        if context.game_pk is not None
    }
    production_evaluation = apply_series_context_policy(
        production_evaluation,
        series_contexts=series_contexts,
        pregame_contexts=pregame_contexts_by_pk,
        top_n=top_n,
    )
    production_evaluation = apply_live_context_policy(
        production_evaluation,
        contexts_by_game_pk=pregame_contexts_by_pk,
        assessed_at=market_timestamp,
        top_n=top_n,
        assessments_by_game_pk=live_context_assessments,
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
        simulation_draws=shadow_draws,
    )
    overlay = fit_adaptive_overlay(evidence_ledger, adaptive_overlay_path)
    shadow_evaluation = apply_overlay_to_evaluation(
        base_shadow_evaluation,
        contexts_by_game_pk={int(context.game_pk): context for context in selected_contexts},
        overlay=overlay,
        top_n=top_n,
    )
    shadow_evaluation = apply_series_context_policy(
        shadow_evaluation,
        series_contexts=series_contexts,
        pregame_contexts=pregame_contexts_by_pk,
        top_n=top_n,
    )
    shadow_evaluation = apply_live_context_policy(
        shadow_evaluation,
        contexts_by_game_pk=pregame_contexts_by_pk,
        assessed_at=market_timestamp,
        top_n=top_n,
        assessments_by_game_pk=live_context_assessments,
    )
    evaluation = combine_production_and_shadow(production_evaluation, shadow_evaluation)

    pa_shadow_evaluation: pd.DataFrame | None = None
    pa_shadow_draws: dict[int, tuple[object, object]] = {}
    if enable_pa_shadow:
        pa_shadow_evaluation = evaluate_pa_shadow_slate(
            historical_features=candidate_historical_features,
            future_features=candidate_future_features,
            moneylines=moneylines,
            contexts_by_game_pk=pregame_contexts_by_pk,
            simulations=int(pa_shadow_simulations or simulations),
            moneyline_weight=pa_shadow_moneyline_weight,
            top_n=top_n,
            simulation_draws=pa_shadow_draws,
        )

    history_record = history_refresh_report.to_record()
    evaluation["history_freshness_status"] = history_refresh_report.status
    evaluation["history_checked_through"] = history_refresh_report.checked_through_date
    evaluation["history_latest_completed_date"] = history_refresh_report.latest_completed_date
    evaluation["history_backfilled_games"] = history_refresh_report.backfilled_games
    evaluation["history_cached_games"] = history_refresh_report.cached_games
    evaluation["history_refresh_metadata"] = [history_record] * len(evaluation)
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
    pa_shadow_csv_path: Path | None = None
    pa_shadow_json_path: Path | None = None
    if pa_shadow_evaluation is not None:
        pa_shadow_csv_path, _, pa_shadow_json_path = write_evaluation_artifacts(
            pa_shadow_evaluation,
            output_dir=output_dir,
            stem=f"mlb_pa_shadow_{captured_slate.game_date}_{timestamp}",
        )

    market_quote_path, simulation_manifest_paths = _persist_platform_outputs(
        captured_slate=captured_slate,
        evaluation=evaluation,
        moneylines=moneylines,
        market_timestamp=market_timestamp,
        market_snapshot_path=market_snapshot_path,
        production_draws=production_draws,
        shadow_draws=shadow_draws,
        sportsbook_name=sportsbook_name,
        market_store_root=market_store_root,
        simulation_store_root=simulation_store_root,
        persist_market_quotes=persist_market_quotes,
        snapshot_input_hashes=snapshot_input_hashes,
        snapshot_metadata=snapshot_metadata,
    )

    pa_shadow_manifest_paths: tuple[str | Path, ...] = ()
    if pa_shadow_evaluation is not None:
        pa_shadow_manifest_paths = _persist_pa_shadow_outputs(
            captured_slate=captured_slate,
            evaluation=pa_shadow_evaluation,
            draws=pa_shadow_draws,
            market_timestamp=market_timestamp,
            market_snapshot_path=market_snapshot_path,
            simulation_store_root=simulation_store_root,
            snapshot_input_hashes=snapshot_input_hashes,
        )

    if record_evidence:
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
    else:
        ledger_path = Path(evidence_ledger)

    return WorkflowResult(
        evaluation=evaluation,
        parlays=parlays,
        csv_path=csv_path,
        parlay_path=parlay_path,
        json_path=json_path,
        market_snapshot_path=market_snapshot_path,
        evidence_ledger_path=ledger_path,
        adaptive_overlay_path=Path(adaptive_overlay_path),
        history_refresh_report=history_refresh_report,
        market_quote_path=market_quote_path,
        simulation_manifest_paths=simulation_manifest_paths,
        pa_shadow_evaluation=pa_shadow_evaluation,
        pa_shadow_csv_path=pa_shadow_csv_path,
        pa_shadow_json_path=pa_shadow_json_path,
        pa_shadow_simulation_manifest_paths=pa_shadow_manifest_paths,
    )
