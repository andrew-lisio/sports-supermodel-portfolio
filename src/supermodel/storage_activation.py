from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tarfile
from typing import Any, Iterable

from .storage import ObjectStore, StorageSettings, create_object_store, create_state_store


@dataclass(frozen=True)
class RuntimeArtifact:
    relative_path: str
    bytes: int
    sha256: str
    category: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorageActivationReport:
    status: str
    generated_at_utc: str
    runtime_root: str
    artifact_count: int
    total_bytes: int
    uploaded_count: int
    skipped_count: int
    manifest_reference: str | None
    artifacts: tuple[RuntimeArtifact, ...]

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [item.to_record() for item in self.artifacts]
        return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _category(relative: Path) -> str:
    head = relative.parts[0] if relative.parts else "other"
    return {
        "markets": "market",
        "simulations": "simulation",
        "reports": "report",
        "snapshots": "raw_snapshot",
        "evidence": "evidence",
        "state": "state",
        "data": "data",
        "models": "model",
    }.get(head, "other")


def discover_runtime_artifacts(
    runtime_root: str | Path = "runtime",
    *,
    include_categories: set[str] | None = None,
) -> tuple[RuntimeArtifact, ...]:
    root = Path(runtime_root)
    if not root.exists():
        return ()
    artifacts: list[RuntimeArtifact] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.endswith((".tmp", ".lock")):
            continue
        relative = path.relative_to(root)
        category = _category(relative)
        if include_categories is not None and category not in include_categories:
            continue
        payload = path.read_bytes()
        artifacts.append(
            RuntimeArtifact(
                relative_path=relative.as_posix(),
                bytes=len(payload),
                sha256=sha256(payload).hexdigest(),
                category=category,
            )
        )
    return tuple(artifacts)


def activate_shared_storage(
    *,
    runtime_root: str | Path = "runtime",
    settings: StorageSettings | None = None,
    object_store: ObjectStore | None = None,
    dry_run: bool = False,
) -> StorageActivationReport:
    active = settings or StorageSettings.from_env()
    store = object_store or create_object_store(active)
    root = Path(runtime_root)
    artifacts = discover_runtime_artifacts(root)
    uploaded = 0
    skipped = 0
    for artifact in artifacts:
        key = f"runtime/{artifact.relative_path}"
        reference = key
        if store.exists(reference):
            try:
                existing = store.get_bytes(reference)
            except OSError:
                existing = b""
            if sha256(existing).hexdigest() == artifact.sha256:
                skipped += 1
                continue
        if not dry_run:
            store.put_bytes(key, (root / artifact.relative_path).read_bytes())
        uploaded += 1

    generated = _utc_now()
    manifest = {
        "schema_version": 1,
        "generated_at_utc": generated,
        "runtime_root": str(root),
        "storage": active.to_record(),
        "dry_run": bool(dry_run),
        "artifacts": [item.to_record() for item in artifacts],
    }
    manifest_reference: str | None = None
    if not dry_run:
        manifest_reference = store.put_bytes(
            f"manifests/runtime-activation/{generated.replace(':', '').replace('-', '')}.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            content_type="application/json",
        )
        state_store = create_state_store(root / "state" / "shared", settings=active)
        state_store.write(
            "storage_activation/latest",
            {**manifest, "manifest_reference": manifest_reference},
        )
    return StorageActivationReport(
        status="DRY_RUN" if dry_run else "PASS",
        generated_at_utc=generated,
        runtime_root=str(root),
        artifact_count=len(artifacts),
        total_bytes=sum(item.bytes for item in artifacts),
        uploaded_count=uploaded,
        skipped_count=skipped,
        manifest_reference=manifest_reference,
        artifacts=artifacts,
    )


def verify_runtime_manifest(
    report: StorageActivationReport,
    *,
    object_store: ObjectStore,
) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[str] = []
    for artifact in report.artifacts:
        key = f"runtime/{artifact.relative_path}"
        if not object_store.exists(key):
            missing.append(artifact.relative_path)
            continue
        payload = object_store.get_bytes(key)
        if sha256(payload).hexdigest() != artifact.sha256:
            mismatched.append(artifact.relative_path)
    return {
        "status": "PASS" if not missing and not mismatched else "FAIL",
        "checked": len(report.artifacts),
        "missing": missing,
        "mismatched": mismatched,
    }


def create_runtime_backup(
    *,
    runtime_root: str | Path = "runtime",
    destination: str | Path,
) -> Path:
    root = Path(runtime_root)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz") as archive:
        if root.exists():
            archive.add(root, arcname="runtime", recursive=True)
    temporary.replace(target)
    return target
