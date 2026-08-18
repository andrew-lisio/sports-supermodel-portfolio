import tarfile

import pytest

from supermodel.storage import LocalObjectStore, StorageSettings
from supermodel.storage_activation import (
    activate_shared_storage,
    create_runtime_backup,
    restore_runtime_backup,
    verify_runtime_backup,
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


def test_runtime_backup_is_verifiable_and_restorable(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "state").mkdir(parents=True)
    (runtime / "state" / "state.json").write_text('{"ok": true}\n', encoding="utf-8")
    target = create_runtime_backup(runtime_root=runtime, destination=tmp_path / "backup.tar.gz")
    assert target.exists()
    assert verify_runtime_backup(target)["status"] == "PASS"

    restored = tmp_path / "restored-runtime"
    restore_runtime_backup(target, runtime_root=restored)
    assert (restored / "state" / "state.json").read_text(encoding="utf-8") == '{"ok": true}\n'


def test_runtime_restore_refuses_nonempty_destination_without_overwrite(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "state.json").write_text("{}", encoding="utf-8")
    backup = create_runtime_backup(runtime_root=runtime, destination=tmp_path / "backup.tar.gz")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_runtime_backup(backup, runtime_root=destination)


def test_runtime_backup_rejects_path_traversal(tmp_path):
    backup = tmp_path / "unsafe.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("unsafe", encoding="utf-8")
    with tarfile.open(backup, "w:gz") as archive:
        archive.add(payload, arcname="../escape.txt")
    report = verify_runtime_backup(backup)
    assert report["status"] == "FAIL"
    assert "unsafe backup member" in report["failures"][0]
