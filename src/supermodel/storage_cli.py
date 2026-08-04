from __future__ import annotations

import argparse
import json
from pathlib import Path

from .postgres_storage import apply_migrations, postgres_healthcheck
from .storage import StorageBackend, StorageSettings, create_object_store
from .storage_activation import activate_shared_storage, create_runtime_backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and initialize Sports SuperModel shared storage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show sanitized storage configuration and health")
    subparsers.add_parser("migrate", help="Apply PostgreSQL schema migrations")
    activate = subparsers.add_parser("activate", help="Upload local runtime artifacts to shared storage")
    activate.add_argument("--runtime-root", type=Path, default=Path("runtime"))
    activate.add_argument("--dry-run", action="store_true")
    backup = subparsers.add_parser("backup", help="Create a compressed local runtime backup")
    backup.add_argument("--runtime-root", type=Path, default=Path("runtime"))
    backup.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = StorageSettings.from_env()
    if args.command == "activate":
        report = activate_shared_storage(
            runtime_root=args.runtime_root,
            settings=settings,
            dry_run=args.dry_run,
        )
        print(json.dumps(report.to_record(), indent=2, sort_keys=True))
        return 0
    if args.command == "backup":
        path = create_runtime_backup(runtime_root=args.runtime_root, destination=args.output)
        print(json.dumps({"status": "PASS", "backup": str(path)}, indent=2, sort_keys=True))
        return 0
    if args.command == "migrate":
        if settings.backend is not StorageBackend.POSTGRES:
            raise RuntimeError(
                "migrate requires SPORTS_SUPERMODEL_STORAGE_BACKEND=postgres"
            )
        applied = apply_migrations(str(settings.database_url))
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "applied_migrations": list(applied),
                    "storage": settings.to_record(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    payload = {"storage": settings.to_record()}
    if settings.backend is StorageBackend.POSTGRES:
        payload["database"] = postgres_healthcheck(str(settings.database_url))
    else:
        object_store = create_object_store(settings)
        payload["database"] = {"status": "LOCAL_FILE_MODE"}
        payload["object_store"] = {
            "status": "PASS",
            "type": type(object_store).__name__,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
