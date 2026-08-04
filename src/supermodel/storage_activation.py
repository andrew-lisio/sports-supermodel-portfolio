from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
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


def _runtime_backup_manifest(runtime_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    if runtime_root.exists():
        for path in sorted(runtime_root.rglob("*")):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            files.append(
                {
                    "relative_path": path.relative_to(runtime_root).as_posix(),
                    "bytes": len(payload),
                    "sha256": sha256(payload).hexdigest(),
                }
            )
    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now(),
        "runtime_root": str(runtime_root),
        "file_count": len(files),
        "total_bytes": sum(int(item["bytes"]) for item in files),
        "files": files,
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
    manifest = _runtime_backup_manifest(root)
    with tarfile.open(temporary, "w:gz") as archive:
        if root.exists():
            archive.add(root, arcname="runtime", recursive=True)
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo("backup_manifest.json")
        info.size = len(payload)
        info.mtime = int(datetime.now(timezone.utc).timestamp())
        archive.addfile(info, io.BytesIO(payload))
    temporary.replace(target)
    return target


def _safe_backup_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe backup member: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise ValueError(f"unsupported backup member type: {member.name}")
        if member.name != "backup_manifest.json" and path.parts[:1] != ("runtime",):
            raise ValueError(f"unexpected backup member: {member.name}")
    return members


def verify_runtime_backup(backup: str | Path) -> dict[str, Any]:
    source = Path(backup)
    failures: list[str] = []
    checked = 0
    try:
        with tarfile.open(source, "r:gz") as archive:
            _safe_backup_members(archive)
            try:
                manifest_member = archive.getmember("backup_manifest.json")
            except KeyError:
                return {
                    "status": "FAIL",
                    "backup": str(source),
                    "failures": ["BACKUP_MANIFEST_MISSING"],
                    "checked_files": 0,
                }
            extracted = archive.extractfile(manifest_member)
            if extracted is None:
                raise ValueError("backup manifest could not be read")
            manifest = json.loads(extracted.read().decode("utf-8"))
            for item in manifest.get("files", []):
                relative = str(item["relative_path"])
                try:
                    member = archive.getmember(f"runtime/{relative}")
                except KeyError:
                    failures.append(f"MISSING:{relative}")
                    continue
                fileobj = archive.extractfile(member)
                if fileobj is None:
                    failures.append(f"UNREADABLE:{relative}")
                    continue
                payload = fileobj.read()
                checked += 1
                if len(payload) != int(item["bytes"]):
                    failures.append(f"SIZE_MISMATCH:{relative}")
                if sha256(payload).hexdigest() != str(item["sha256"]):
                    failures.append(f"HASH_MISMATCH:{relative}")
    except (OSError, tarfile.TarError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "backup": str(source),
            "failures": [f"BACKUP_INVALID:{type(exc).__name__}:{exc}"],
            "checked_files": checked,
        }
    return {
        "status": "PASS" if not failures else "FAIL",
        "backup": str(source),
        "failures": failures,
        "checked_files": checked,
    }


def restore_runtime_backup(
    backup: str | Path,
    *,
    runtime_root: str | Path = "runtime",
    overwrite: bool = False,
) -> Path:
    verification = verify_runtime_backup(backup)
    if verification["status"] != "PASS":
        raise RuntimeError(
            "runtime backup verification failed: " + ", ".join(verification["failures"])
        )
    target = Path(runtime_root)
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise FileExistsError(
            f"runtime destination {target} is not empty; pass overwrite=True to replace it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary_dir:
        staging = Path(temporary_dir)
        with tarfile.open(backup, "r:gz") as archive:
            members = _safe_backup_members(archive)
            for member in members:
                if member.name == "backup_manifest.json":
                    continue
                destination = staging.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ValueError(f"unsupported backup member type: {member.name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"backup member could not be read: {member.name}")
                with destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        restored = staging / "runtime"
        if not restored.exists():
            restored.mkdir()
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(restored), str(target))
    return target
