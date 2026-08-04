from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator

from ._version import __version__
from .live_context import (
    LiveContextAssessment,
    live_context_game_fingerprints,
    refresh_live_context,
)
from .live_mlb import MLBStatsHTTPClient
from .odds_provider import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_MARKETS,
    OddsProviderError,
    TheOddsAPIClient,
    refresh_the_odds_api,
)
from .odds_input import ManualMoneyline
from .providers import PregameContext
from .refresh_orchestrator import PlatformRefreshReport, refresh_platform_data
from .simulation_store import LocalSimulationSnapshotStore
from .storage import (
    ObjectBackend,
    StorageBackend,
    StorageSettings,
    acquire_publisher_lock,
    create_object_store,
    create_simulation_snapshot_store,
    create_state_store,
)
from .workflow import (
    CapturedSlate,
    WorkflowResult,
    _candidate_model_commit,
    _repository_commit,
    capture_official_slate,
    evaluate_captured_slate,
)


@dataclass(frozen=True)
class SlatePublishReport:
    status: str
    slate_date: str
    generated_at_utc: str
    captured_at_utc: str
    simulations: int
    eligible_game_pks: tuple[int, ...]
    published_game_pks: tuple[int, ...]
    unchanged_game_pks: tuple[int, ...]
    excluded_games: tuple[dict[str, Any], ...]
    refresh_status: str
    refresh_state_path: str | None
    publisher_state_path: str
    report_path: str
    evaluation_artifact: str | None
    simulation_manifests: tuple[str, ...]
    market_quotes_persisted: bool
    live_context_status: str
    live_context_provider: str | None
    live_context_snapshot_path: str | None
    live_context_blocked_game_pks: tuple[int, ...]
    odds_refresh_status: str
    odds_provider: str | None
    odds_quotes_received: int
    odds_quotes_changed: int
    odds_sportsbooks: tuple[str, ...]
    odds_snapshot_path: str | None
    odds_unmatched_events: tuple[dict[str, Any], ...]
    next_game_start_utc: str | None
    evidence_recorded: bool
    storage_backend: str
    shared_state_ref: str | None
    shared_report_ref: str | None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "eligible_game_pks",
            "published_game_pks",
            "unchanged_game_pks",
            "excluded_games",
            "simulation_manifests",
            "live_context_blocked_game_pks",
            "odds_sportsbooks",
            "odds_unmatched_events",
        ):
            payload[key] = list(payload[key])
        return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _context_exclusion_reason(context: PregameContext, captured_at: datetime) -> str | None:
    if context.game_pk is None:
        return "missing_game_pk"
    status = " ".join(
        str(value or "")
        for value in (context.status_abstract, context.status_detailed)
    ).lower()
    terminal_tokens = (
        "final",
        "completed",
        "game over",
        "cancelled",
        "canceled",
        "postponed",
        "suspended",
        "in progress",
        "live",
    )
    if any(token in status for token in terminal_tokens):
        return f"status:{status.strip() or 'unknown'}"
    start = _parse_start(context.game_datetime)
    if start is None:
        return "missing_game_time"
    if captured_at >= start:
        return "scheduled_start_reached"
    return None


def _stable_context_record(context: PregameContext) -> dict[str, Any]:
    record = context.to_record()
    record.pop("provenance", None)
    for key in list(record):
        if key.endswith("_snapshot_path") or key.endswith("_snapshot_sha256"):
            record.pop(key, None)
    return record


def _update_digest_from_path(digest: Any, path: Path, *, root: Path | None = None) -> None:
    if not path.exists() or not path.is_file():
        return
    label = str(path.relative_to(root)) if root is not None else str(path)
    digest.update(label.replace("\\", "/").encode("utf-8"))
    digest.update(path.read_bytes())


def model_data_fingerprint(
    *,
    data_dir: str | Path,
    history_cache_path: str | Path,
) -> str:
    """Fingerprint predictive code identity and historical inputs.

    Pitching-context data is intentionally excluded because the rejected RC3 fields do
    not have prediction authority. When those features are redesigned and activated,
    their canonical dataset must be added here.
    """

    digest = sha256()
    digest.update(f"package={__version__}".encode("utf-8"))
    digest.update(f"production_commit={_repository_commit()}".encode("utf-8"))
    digest.update(f"shadow_commit={_candidate_model_commit()}".encode("utf-8"))
    root = Path(data_dir)
    for path in sorted(root.rglob("*.csv")):
        _update_digest_from_path(digest, path, root=root)
    _update_digest_from_path(digest, Path(history_cache_path))
    for path in (
        Path("config/final_candidate.yaml"),
        Path("config/feature_registry.yaml"),
        Path("config/execution.yaml"),
    ):
        _update_digest_from_path(digest, path)
    return digest.hexdigest()


def game_input_fingerprint(
    *,
    context: PregameContext,
    model_data_hash: str,
    live_context_hash: str | None = None,
) -> str:
    payload = {
        "schema": 1,
        "model_data_hash": model_data_hash,
        "live_context_hash": live_context_hash,
        "context": _stable_context_record(context),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


@contextmanager
def publisher_lock(
    path: str | Path,
    *,
    now: datetime,
    stale_after: timedelta = timedelta(hours=2),
) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "created_at": _utc_iso(now)}
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(existing["created_at"]).replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            created = now
        if created.tzinfo is None or created.utcoffset() is None:
            created = created.replace(tzinfo=timezone.utc)
        if now - created.astimezone(timezone.utc) <= stale_after:
            raise RuntimeError(f"Slate publisher is already running; lock exists at {lock_path}")
        lock_path.unlink(missing_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _neutral_moneylines(contexts: list[PregameContext]) -> list[ManualMoneyline]:
    return [
        ManualMoneyline(
            game_date=context.game_date,
            away_team=context.away_team,
            home_team=context.home_team,
            away_odds=100,
            home_odds=100,
            game_pk=int(context.game_pk),
        )
        for context in contexts
    ]


def _report_path(root: Path, slate_date: str, timestamp: datetime) -> Path:
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return root / slate_date / f"{stamp}.json"


def publish_slate(
    *,
    slate_date: str,
    data_dir: str | Path = "data/2026",
    snapshot_dir: str | Path = "runtime/snapshots",
    output_dir: str | Path = "runtime/reports",
    history_cache_path: str | Path = "runtime/data/mlb_completed_games.csv",
    pitching_context_path: str | Path = "runtime/data/mlb_pitching_context.csv",
    pitching_cache_dir: str | Path = "runtime/cache/mlb_pitching_feeds",
    refresh_state_path: str | Path = "runtime/state/platform_refresh.json",
    publisher_state_path: str | Path = "runtime/state/slate_publisher.json",
    publisher_report_root: str | Path = "runtime/reports/slate_publisher",
    publisher_lock_path: str | Path = "runtime/state/slate_publisher.lock",
    market_store_root: str | Path = "runtime/markets",
    simulation_store_root: str | Path = "runtime/simulations",
    evidence_ledger: str | Path = "runtime/evidence/prospective.jsonl",
    adaptive_overlay_path: str | Path = "runtime/models/v2_4_adaptive_overlay.json",
    simulations: int = 100_000,
    top_n: int = 5,
    force: bool = False,
    refresh: bool = True,
    client: MLBStatsHTTPClient | None = None,
    captured_at: datetime | None = None,
    progress_callback: Callable[[int, int, int, str], None] | None = None,
    odds_api_key: str | None = None,
    odds_bookmakers: tuple[str, ...] = DEFAULT_BOOKMAKERS,
    odds_markets: tuple[str, ...] = DEFAULT_MARKETS,
    odds_snapshot_root: str | Path = "runtime/snapshots/odds/the_odds_api",
    live_context_root: str | Path = "runtime/live_context",
    odds_client: TheOddsAPIClient | None = None,
    require_odds: bool = False,
) -> SlatePublishReport:
    """Refresh inputs and centrally publish changed pregame simulations.

    The publisher never persists synthetic prices and never records market evidence.
    Real/provider quotes remain a separate append-only stream that reprices the saved
    distributions without triggering another model run.
    """

    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    api_client = client or MLBStatsHTTPClient()

    storage_settings = StorageSettings.from_env()
    object_store = create_object_store(storage_settings)
    with acquire_publisher_lock(
        publisher_lock_path, now=timestamp, settings=storage_settings
    ):
        refresh_report: PlatformRefreshReport | None = None
        if refresh:
            refresh_report = refresh_platform_data(
                slate_date=slate_date,
                data_dir=data_dir,
                snapshot_dir=snapshot_dir,
                history_cache=history_cache_path,
                pitching_context_path=pitching_context_path,
                pitching_cache_dir=pitching_cache_dir,
                state_path=refresh_state_path,
                client=api_client,
                progress_callback=progress_callback,
            )

        captured = capture_official_slate(
            game_date=slate_date,
            snapshot_dir=snapshot_dir,
            client=api_client,
            captured_at=timestamp,
        )
        live_context_report = refresh_live_context(
            slate_date=slate_date,
            snapshot_dir=snapshot_dir,
            report_root=live_context_root,
            client=api_client,
            captured_at=timestamp,
            contexts=captured.contexts,
        )
        live_context_assessments: dict[int, LiveContextAssessment] = {
            int(item.game_pk): item for item in live_context_report.assessments
        }
        all_contexts_by_pk = {
            int(context.game_pk): context
            for context in captured.contexts
            if context.game_pk is not None
        }
        live_context_hashes = live_context_game_fingerprints(
            live_context_report, contexts_by_game_pk=all_contexts_by_pk
        )
        eligible: list[PregameContext] = []
        excluded: list[dict[str, Any]] = []
        for context in captured.contexts:
            reason = _context_exclusion_reason(context, timestamp)
            if reason is None:
                eligible.append(context)
            else:
                excluded.append(
                    {
                        "game_pk": context.game_pk,
                        "away_team": context.away_team,
                        "home_team": context.home_team,
                        "reason": reason,
                    }
                )

        odds_status = "NOT_CONFIGURED"
        odds_provider: str | None = None
        odds_quotes_received = 0
        odds_quotes_changed = 0
        odds_sportsbooks: tuple[str, ...] = ()
        odds_snapshot_path: str | None = None
        odds_unmatched_events: tuple[dict[str, Any], ...] = ()
        configured_key = odds_api_key or os.environ.get("SPORTS_SUPERMODEL_ODDS_API_KEY")
        if odds_client is not None or configured_key:
            odds_provider = "the_odds_api"
            try:
                provider_client = odds_client or TheOddsAPIClient(str(configured_key))
                odds_report = refresh_the_odds_api(
                    client=provider_client,
                    slate_date=slate_date,
                    contexts=eligible,
                    market_store_root=market_store_root,
                    raw_snapshot_root=odds_snapshot_root,
                    bookmakers=odds_bookmakers,
                    markets=odds_markets,
                    captured_at=timestamp,
                )
                odds_status = odds_report.status
                odds_quotes_received = odds_report.quotes_received
                odds_quotes_changed = odds_report.quotes_changed
                odds_sportsbooks = odds_report.sportsbooks
                odds_snapshot_path = odds_report.raw_snapshot_path
                odds_unmatched_events = odds_report.unmatched_events
            except (OddsProviderError, ValueError) as exc:
                odds_status = f"ERROR:{exc}"
                if require_odds:
                    raise

        model_hash = model_data_fingerprint(
            data_dir=data_dir,
            history_cache_path=history_cache_path,
        )
        hashes = {
            int(context.game_pk): game_input_fingerprint(
                context=context,
                model_data_hash=model_hash,
                live_context_hash=live_context_hashes.get(int(context.game_pk)),
            )
            for context in eligible
        }
        snapshot_store = (
            LocalSimulationSnapshotStore(simulation_store_root)
            if storage_settings.backend is StorageBackend.LOCAL
            else create_simulation_snapshot_store(
                simulation_store_root, settings=storage_settings
            )
        )
        changed: list[PregameContext] = []
        unchanged: list[int] = []
        for context in eligible:
            game_pk = int(context.game_pk)
            latest_production = snapshot_store.latest(game_pk, model_track="production")
            latest_shadow = snapshot_store.latest(game_pk, model_track="shadow")
            snapshots_current = all(
                snapshot is not None
                and snapshot.input_snapshot_hash == hashes[game_pk]
                and int(snapshot.simulations) == int(simulations)
                for snapshot in (latest_production, latest_shadow)
            )
            if force or not snapshots_current:
                changed.append(context)
            else:
                unchanged.append(game_pk)

        workflow_result: WorkflowResult | None = None
        if changed:
            workflow_result = evaluate_captured_slate(
                captured_slate=captured,
                moneylines=_neutral_moneylines(changed),
                data_dir=data_dir,
                snapshot_dir=snapshot_dir,
                output_dir=output_dir,
                evidence_ledger=evidence_ledger,
                adaptive_overlay_path=adaptive_overlay_path,
                history_cache_path=history_cache_path,
                simulations=int(simulations),
                top_n=int(top_n),
                include_parlays=False,
                input_source="scheduled_backend:simulation_only",
                market_captured_at=timestamp,
                client=api_client,
                sportsbook_name="MODEL_ONLY",
                market_store_root=market_store_root,
                simulation_store_root=simulation_store_root,
                persist_market_quotes=False,
                record_evidence=False,
                snapshot_input_hashes=hashes,
                snapshot_metadata={
                    "publication_mode": "scheduled_backend",
                    "provider_quotes_required_for_value": True,
                    "model_data_hash": model_hash,
                    "live_context_provider": live_context_report.provider,
                    "live_context_captured_at": live_context_report.captured_at_utc,
                    "live_context_snapshot_path": live_context_report.snapshot_path,
                },
                live_context_assessments=live_context_assessments,
            )

        if not eligible:
            status = "NO_PREGAME_GAMES"
        elif not changed:
            status = "PRICES_UPDATED" if odds_quotes_changed else "SKIPPED_UNCHANGED"
        else:
            status = "PASS"

        starts = [
            start
            for start in (_parse_start(context.game_datetime) for context in eligible)
            if start is not None
        ]
        next_game_start = _utc_iso(min(starts)) if starts else None

        report_path = _report_path(Path(publisher_report_root), slate_date, timestamp)
        evaluation_artifact_ref = (
            str(workflow_result.json_path) if workflow_result is not None else None
        )
        if (
            workflow_result is not None
            and (
                storage_settings.backend is StorageBackend.POSTGRES
                or storage_settings.object_backend is ObjectBackend.S3
            )
        ):
            evaluation_artifact_ref = object_store.put_bytes(
                f"reports/evaluations/{slate_date}/{workflow_result.json_path.name}",
                workflow_result.json_path.read_bytes(),
                content_type="application/json",
            )
        report = SlatePublishReport(
            status=status,
            slate_date=slate_date,
            generated_at_utc=_utc_iso(datetime.now(timezone.utc)),
            captured_at_utc=_utc_iso(timestamp),
            simulations=int(simulations),
            eligible_game_pks=tuple(sorted(hashes)),
            published_game_pks=tuple(sorted(int(context.game_pk) for context in changed)),
            unchanged_game_pks=tuple(sorted(unchanged)),
            excluded_games=tuple(excluded),
            refresh_status=refresh_report.status if refresh_report is not None else "SKIPPED",
            refresh_state_path=(
                refresh_report.state_path if refresh_report is not None else None
            ),
            publisher_state_path=str(Path(publisher_state_path)),
            report_path=str(report_path),
            evaluation_artifact=evaluation_artifact_ref,
            simulation_manifests=(
                tuple(str(path) for path in workflow_result.simulation_manifest_paths)
                if workflow_result is not None
                else ()
            ),
            market_quotes_persisted=bool(odds_quotes_changed),
            live_context_status=live_context_report.status,
            live_context_provider=live_context_report.provider,
            live_context_snapshot_path=live_context_report.snapshot_path,
            live_context_blocked_game_pks=live_context_report.blocked_game_pks,
            odds_refresh_status=odds_status,
            odds_provider=odds_provider,
            odds_quotes_received=odds_quotes_received,
            odds_quotes_changed=odds_quotes_changed,
            odds_sportsbooks=odds_sportsbooks,
            odds_snapshot_path=odds_snapshot_path,
            odds_unmatched_events=odds_unmatched_events,
            next_game_start_utc=next_game_start,
            evidence_recorded=False,
            storage_backend=str(storage_settings.backend),
            shared_state_ref=None,
            shared_report_ref=None,
        )
        local_state_payload = {
            **report.to_record(),
            "latest_game_input_hashes": {str(key): value for key, value in hashes.items()},
        }
        _write_json_atomic(report_path, report.to_record())
        _write_json_atomic(Path(publisher_state_path), local_state_payload)

        report_key = (
            f"reports/slate_publisher/{slate_date}/"
            f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        shared_report_ref = object_store.put_bytes(
            report_key,
            (json.dumps(report.to_record(), indent=2, sort_keys=True) + "\n").encode("utf-8"),
            content_type="application/json",
        )
        state_store = create_state_store(
            Path(publisher_state_path).parent / "shared",
            settings=storage_settings,
        )
        shared_state_ref = state_store.write(
            f"slate_publisher/{slate_date}/latest",
            local_state_payload,
        )
        state_store.write("slate_publisher/latest", local_state_payload)
        report = replace(
            report,
            shared_state_ref=shared_state_ref,
            shared_report_ref=shared_report_ref,
        )
        final_payload = report.to_record()
        _write_json_atomic(report_path, final_payload)
        _write_json_atomic(
            Path(publisher_state_path),
            {
                **final_payload,
                "latest_game_input_hashes": {str(key): value for key, value in hashes.items()},
            },
        )
        object_store.put_bytes(
            report_key,
            (json.dumps(final_payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            content_type="application/json",
        )
        state_store.write(
            f"slate_publisher/{slate_date}/latest",
            {
                **final_payload,
                "latest_game_input_hashes": {str(key): value for key, value in hashes.items()},
            },
        )
        state_store.write(
            "slate_publisher/latest",
            {
                **final_payload,
                "latest_game_input_hashes": {str(key): value for key, value in hashes.items()},
            },
        )
        return report
