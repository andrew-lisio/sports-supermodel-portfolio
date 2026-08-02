from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any, Iterator, Protocol, runtime_checkable


class StorageBackend(StrEnum):
    LOCAL = "local"
    POSTGRES = "postgres"


class ObjectBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class StorageSettings:
    """Runtime storage configuration.

    Local mode remains the default so the repository can be used offline. Hosted
    deployments opt into PostgreSQL and an S3-compatible object store through
    environment variables. Secrets are intentionally never included in ``to_record``.
    """

    backend: StorageBackend = StorageBackend.LOCAL
    database_url: str | None = None
    object_backend: ObjectBackend = ObjectBackend.LOCAL
    local_object_root: Path = Path("runtime/objects")
    s3_bucket: str | None = None
    s3_prefix: str = "sports-supermodel"
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_force_path_style: bool = False

    @classmethod
    def from_env(cls) -> "StorageSettings":
        backend = StorageBackend(
            os.environ.get("SPORTS_SUPERMODEL_STORAGE_BACKEND", "local").strip().lower()
        )
        object_backend = ObjectBackend(
            os.environ.get("SPORTS_SUPERMODEL_OBJECT_BACKEND", "local").strip().lower()
        )
        settings = cls(
            backend=backend,
            database_url=(os.environ.get("DATABASE_URL") or None),
            object_backend=object_backend,
            local_object_root=Path(
                os.environ.get("SPORTS_SUPERMODEL_OBJECT_ROOT", "runtime/objects")
            ),
            s3_bucket=(os.environ.get("SPORTS_SUPERMODEL_S3_BUCKET") or None),
            s3_prefix=os.environ.get(
                "SPORTS_SUPERMODEL_S3_PREFIX", "sports-supermodel"
            ).strip("/"),
            s3_region=(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None),
            s3_endpoint_url=(
                os.environ.get("SPORTS_SUPERMODEL_S3_ENDPOINT_URL") or None
            ),
            s3_force_path_style=_env_bool(
                "SPORTS_SUPERMODEL_S3_FORCE_PATH_STYLE", False
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.backend is StorageBackend.POSTGRES and not self.database_url:
            raise RuntimeError(
                "SPORTS_SUPERMODEL_STORAGE_BACKEND=postgres requires DATABASE_URL"
            )
        if self.object_backend is ObjectBackend.S3 and not self.s3_bucket:
            raise RuntimeError(
                "SPORTS_SUPERMODEL_OBJECT_BACKEND=s3 requires "
                "SPORTS_SUPERMODEL_S3_BUCKET"
            )

    def to_record(self) -> dict[str, Any]:
        return {
            "backend": str(self.backend),
            "database_configured": bool(self.database_url),
            "object_backend": str(self.object_backend),
            "local_object_root": str(self.local_object_root),
            "s3_bucket": self.s3_bucket,
            "s3_prefix": self.s3_prefix,
            "s3_region": self.s3_region,
            "s3_endpoint_url_configured": bool(self.s3_endpoint_url),
            "s3_force_path_style": self.s3_force_path_style,
        }


@runtime_checkable
class ObjectStore(Protocol):
    def put_bytes(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str: ...

    def get_bytes(self, reference: str) -> bytes: ...

    def exists(self, reference: str) -> bool: ...


class LocalObjectStore:
    def __init__(self, root: str | Path = "runtime/objects") -> None:
        self.root = Path(root)

    def _path(self, key_or_reference: str) -> Path:
        value = str(key_or_reference)
        if value.startswith("file://"):
            return Path(value[7:])
        clean = value.replace("\\", "/").lstrip("/")
        if ".." in Path(clean).parts:
            raise ValueError("object keys cannot traverse parent directories")
        return self.root / clean

    def put_bytes(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return f"file://{path.resolve()}"

    def get_bytes(self, reference: str) -> bytes:
        return self._path(reference).read_bytes()

    def exists(self, reference: str) -> bool:
        return self._path(reference).is_file()


class S3ObjectStore:
    """S3-compatible object storage with an injectable client for tests.

    The implementation works with AWS S3 and providers such as Cloudflare R2,
    Backblaze B2, MinIO, or Railway-compatible S3 services.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "sports-supermodel",
        region: str | None = None,
        endpoint_url: str | None = None,
        force_path_style: bool = False,
        client: Any | None = None,
    ) -> None:
        if not str(bucket).strip():
            raise ValueError("bucket is required")
        self.bucket = str(bucket).strip()
        self.prefix = str(prefix).strip("/")
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "S3 storage requires the 'storage' optional dependencies"
                ) from exc
            config = Config(s3={"addressing_style": "path" if force_path_style else "auto"})
            client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint_url,
                config=config,
            )
        self.client = client

    def _key(self, key_or_reference: str) -> str:
        value = str(key_or_reference)
        if value.startswith("s3://"):
            without_scheme = value[5:]
            bucket, _, key = without_scheme.partition("/")
            if bucket != self.bucket:
                raise ValueError(
                    f"object reference bucket {bucket!r} does not match {self.bucket!r}"
                )
            return key
        clean = value.replace("\\", "/").lstrip("/")
        return f"{self.prefix}/{clean}" if self.prefix else clean

    def put_bytes(
        self,
        key: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        object_key = self._key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=payload,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{object_key}"

    def get_bytes(self, reference: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(reference))
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def exists(self, reference: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(reference))
        except Exception as exc:  # pragma: no cover - provider-specific error classes
            response = getattr(exc, "response", {}) or {}
            code = str((response.get("Error") or {}).get("Code") or "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True


@runtime_checkable
class JsonStateStore(Protocol):
    def write(self, key: str, payload: dict[str, Any]) -> str: ...

    def read(self, key: str) -> dict[str, Any] | None: ...


class LocalJsonStateStore:
    def __init__(self, root: str | Path = "runtime/state/shared") -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        clean = str(key).replace("\\", "/").strip("/")
        if ".." in Path(clean).parts:
            raise ValueError("state keys cannot traverse parent directories")
        return self.root / f"{clean}.json"

    def write(self, key: str, payload: dict[str, Any]) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return str(path)

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"state document {key!r} must be a JSON object")
        return value


def create_object_store(settings: StorageSettings | None = None) -> ObjectStore:
    active = settings or StorageSettings.from_env()
    if active.object_backend is ObjectBackend.S3:
        return S3ObjectStore(
            bucket=str(active.s3_bucket),
            prefix=active.s3_prefix,
            region=active.s3_region,
            endpoint_url=active.s3_endpoint_url,
            force_path_style=active.s3_force_path_style,
        )
    return LocalObjectStore(active.local_object_root)


def create_market_quote_store(
    local_root: str | Path = "runtime/markets",
    *,
    settings: StorageSettings | None = None,
):
    active = settings or StorageSettings.from_env()
    if active.backend is StorageBackend.POSTGRES:
        from .postgres_storage import PostgresMarketQuoteStore

        return PostgresMarketQuoteStore(str(active.database_url))
    from .market_store import LocalMarketQuoteStore

    return LocalMarketQuoteStore(local_root)


def create_simulation_snapshot_store(
    local_root: str | Path = "runtime/simulations",
    *,
    settings: StorageSettings | None = None,
    object_store: ObjectStore | None = None,
):
    active = settings or StorageSettings.from_env()
    if active.backend is StorageBackend.POSTGRES:
        from .postgres_storage import PostgresSimulationSnapshotStore

        return PostgresSimulationSnapshotStore(
            str(active.database_url),
            object_store=object_store or create_object_store(active),
        )
    from .simulation_store import LocalSimulationSnapshotStore

    return LocalSimulationSnapshotStore(local_root)


def create_state_store(
    local_root: str | Path = "runtime/state/shared",
    *,
    settings: StorageSettings | None = None,
) -> JsonStateStore:
    active = settings or StorageSettings.from_env()
    if active.backend is StorageBackend.POSTGRES:
        from .postgres_storage import PostgresJsonStateStore

        return PostgresJsonStateStore(str(active.database_url))
    return LocalJsonStateStore(local_root)


@contextmanager
def acquire_publisher_lock(
    local_path: str | Path,
    *,
    now: datetime,
    stale_after: timedelta = timedelta(hours=2),
    settings: StorageSettings | None = None,
    lock_name: str = "sports-supermodel:slate-publisher",
) -> Iterator[None]:
    active = settings or StorageSettings.from_env()
    if active.backend is StorageBackend.POSTGRES:
        from .postgres_storage import postgres_advisory_lock

        with postgres_advisory_lock(str(active.database_url), lock_name=lock_name):
            yield
        return

    # Lazy import avoids a circular dependency while retaining the existing local lock.
    from .publisher import publisher_lock

    with publisher_lock(local_path, now=now, stale_after=stale_after):
        yield
