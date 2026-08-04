from pathlib import Path

from supermodel.storage import LocalObjectStore, StorageSettings
from supermodel.storage_activation import (
    activate_shared_storage,
    create_runtime_backup,
    verify_runtime_manifest,
)


def test_local_activation_is_idempotent_and_verifiable(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "reports").mkdir(parents=True)
    (runtime / "reports" / "a.json").write_text('{"ok": true}\n', encoding="utf-8")
    store = LocalObjectStore(tmp_path / "objects")
    settings = StorageSettings(local_object_root=tmp_path / "objects")
    first = activate_shared_storage(
        runtime_root=runtime,
        settings=settings,
        object_store=store,
    )
    assert first.status == "PASS"
    assert first.uploaded_count == 1
    assert verify_runtime_manifest(first, object_store=store)["status"] == "PASS"

    second = activate_shared_storage(
        runtime_root=runtime,
        settings=settings,
        object_store=store,
    )
    assert second.skipped_count == 1


def test_runtime_backup_contains_runtime_tree(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "state.json").write_text("{}", encoding="utf-8")
    target = create_runtime_backup(runtime_root=runtime, destination=tmp_path / "backup.tar.gz")
    assert target.exists()
    assert target.stat().st_size > 0
