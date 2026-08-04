from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterator

from .storage import StorageBackend, StorageSettings


@dataclass(frozen=True)
class ServiceHealth:
    status: str
    service: str
    checked_at_utc: str
    version: str
    git_commit: str
    storage_backend: str
    object_backend: str
    details: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobRunRecord:
    job_run_id: str
    job_name: str
    started_at_utc: str
    finished_at_utc: str | None
    status: str
    git_commit: str
    payload: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git_commit() -> str:
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


def build_health(
    service: str,
    *,
    settings: StorageSettings | None = None,
    require_shared_storage: bool = False,
    require_odds_key: bool = False,
) -> ServiceHealth:
    active = settings or StorageSettings.from_env()
    failures: list[str] = []
    warnings: list[str] = []
    if require_shared_storage and active.backend is not StorageBackend.POSTGRES:
        failures.append("POSTGRES_NOT_CONFIGURED")
    if require_odds_key and not os.environ.get("SPORTS_SUPERMODEL_ODDS_API_KEY"):
        failures.append("ODDS_API_KEY_NOT_CONFIGURED")
    if active.backend is StorageBackend.LOCAL:
        warnings.append("LOCAL_FILE_MODE")
    status = "PASS" if not failures else "FAIL"
    from ._version import __version__

    return ServiceHealth(
        status=status,
        service=service,
        checked_at_utc=_utc_now(),
        version=__version__,
        git_commit=git_commit(),
        storage_backend=str(active.backend),
        object_backend=str(active.object_backend),
        details={"failures": failures, "warnings": warnings},
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def job_run(
    job_name: str,
    *,
    root: str | Path = "runtime/jobs",
    payload: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    started = _utc_now()
    identity = sha256(f"{job_name}:{started}:{os.getpid()}".encode("utf-8")).hexdigest()[:24]
    state = dict(payload or {})
    record = JobRunRecord(
        job_run_id=identity,
        job_name=job_name,
        started_at_utc=started,
        finished_at_utc=None,
        status="RUNNING",
        git_commit=git_commit(),
        payload=state,
    )
    path = Path(root) / job_name / f"{identity}.json"
    _atomic_json(path, record.to_record())
    try:
        yield state
    except Exception as exc:
        finished = JobRunRecord(
            job_run_id=identity,
            job_name=job_name,
            started_at_utc=started,
            finished_at_utc=_utc_now(),
            status="FAIL",
            git_commit=record.git_commit,
            payload={**state, "error_type": type(exc).__name__, "message": str(exc)},
        )
        _atomic_json(path, finished.to_record())
        raise
    else:
        finished = JobRunRecord(
            job_run_id=identity,
            job_name=job_name,
            started_at_utc=started,
            finished_at_utc=_utc_now(),
            status="PASS",
            git_commit=record.git_commit,
            payload=state,
        )
        _atomic_json(path, finished.to_record())
