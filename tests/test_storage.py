from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path

import numpy as np
import pytest

from supermodel.market_schema import MarketQuote
from supermodel.market_store import LocalMarketQuoteStore
from supermodel.postgres_storage import (
    PostgresJsonStateStore,
    PostgresMarketQuoteStore,
    PostgresSimulationSnapshotStore,
    migration_names,
    postgres_advisory_lock,
)
from supermodel.simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot
from supermodel.storage import (
    LocalJsonStateStore,
    LocalObjectStore,
    ObjectBackend,
    S3ObjectStore,
    StorageBackend,
    StorageSettings,
    create_market_quote_store,
    create_simulation_snapshot_store,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        del ContentType
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {}


class FakeDatabase:
    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.simulations: dict[str, dict] = {}
        self.market_history: dict[str, dict] = {}
        self.locked = False

    def connect(self, dsn: str):
        assert dsn == "postgresql://test"
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database

    def cursor(self):
        return FakeCursor(self.database)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class FakeCursor:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split()).lower()
        params = params or ()
        self.rows = []
        if normalized.startswith("insert into supermodel.platform_state"):
            self.database.states[str(params[0])] = str(params[1])
        elif normalized.startswith("select payload from supermodel.platform_state"):
            payload = self.database.states.get(str(params[0]))
            self.rows = [] if payload is None else [(payload,)]
        elif normalized.startswith("insert into supermodel.simulation_snapshots"):
            self.database.simulations[str(params[0])] = {
                "snapshot_id": str(params[0]),
                "game_pk": int(params[1]),
                "event_date": params[2],
                "model_track": str(params[3]),
                "created_at": str(params[7]),
                "object_ref": str(params[11]),
                "manifest": str(params[12]),
            }
        elif "from supermodel.simulation_snapshots" in normalized:
            values = list(self.database.simulations.values())
            if "where snapshot_id = %s" in normalized:
                values = [value for value in values if value["snapshot_id"] == str(params[0])]
            elif "where game_pk = %s and model_track = %s" in normalized:
                values = [
                    value
                    for value in values
                    if value["game_pk"] == int(params[0])
                    and value["model_track"] == str(params[1])
                ]
                values.sort(key=lambda value: value["created_at"], reverse=True)
                values = values[:1]
            elif "event_date = %s" in normalized:
                values = [
                    value
                    for value in values
                    if value["model_track"] == str(params[0])
                    and value["event_date"] == params[1]
                ]
            else:
                values = [
                    value for value in values if value["model_track"] == str(params[0])
                ]
            self.rows = [(value["manifest"], value["object_ref"]) for value in values]
        elif normalized.startswith("insert into supermodel.market_quote_history"):
            self.database.market_history[str(params[0])] = {
                "event_date": str(params[1]),
                "captured_at": str(params[9]),
                "payload": str(params[12]),
            }
        elif "from supermodel.market_quote_history" in normalized:
            event_date = str(params[0])
            values = [
                value
                for value in self.database.market_history.values()
                if value["event_date"] == event_date
            ]
            values.sort(key=lambda value: value["captured_at"])
            self.rows = [(value["payload"],) for value in values]
        elif "from supermodel.current_market_quotes" in normalized:
            self.rows = []
        elif "from supermodel.provider_market_snapshots" in normalized:
            self.rows = []
        elif normalized.startswith("select pg_try_advisory_lock"):
            acquired = not self.database.locked
            self.database.locked = True
            self.rows = [(acquired,)]
        elif normalized.startswith("select pg_advisory_unlock"):
            self.database.locked = False
            self.rows = [(True,)]
        else:
            raise AssertionError(f"Unexpected SQL in fake database: {normalized}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def _snapshot() -> SimulationSnapshot:
    return SimulationSnapshot(
        game_pk=99,
        away_team="ATL",
        home_team="MIA",
        model_track="production",
        model_version="2.3.3",
        git_commit="abc",
        input_snapshot_hash="hash",
        created_at=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        random_seed=7,
        away_runs=np.array([3, 4, 5], dtype=int),
        home_runs=np.array([2, 4, 1], dtype=int),
        away_win_probability=0.6,
        home_win_probability=0.4,
        metadata={"game_date": "2026-08-02"},
    )


def test_storage_settings_defaults_to_local(monkeypatch):
    for key in (
        "SPORTS_SUPERMODEL_STORAGE_BACKEND",
        "SPORTS_SUPERMODEL_OBJECT_BACKEND",
        "DATABASE_URL",
        "SPORTS_SUPERMODEL_S3_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = StorageSettings.from_env()
    assert settings.backend is StorageBackend.LOCAL
    assert settings.object_backend is ObjectBackend.LOCAL


def test_postgres_storage_requires_database_url(monkeypatch):
    monkeypatch.setenv("SPORTS_SUPERMODEL_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        StorageSettings.from_env()


def test_s3_storage_requires_bucket(monkeypatch):
    monkeypatch.setenv("SPORTS_SUPERMODEL_OBJECT_BACKEND", "s3")
    monkeypatch.delenv("SPORTS_SUPERMODEL_S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        StorageSettings.from_env()


def test_settings_record_never_exposes_database_url():
    settings = StorageSettings(
        backend=StorageBackend.POSTGRES,
        database_url="postgresql://user:secret@example/db",
    )
    record = settings.to_record()
    assert record["database_configured"] is True
    assert "secret" not in str(record)


def test_local_object_store_round_trip(tmp_path):
    store = LocalObjectStore(tmp_path)
    reference = store.put_bytes("reports/example.json", b"{}", content_type="application/json")
    assert store.exists(reference)
    assert store.get_bytes(reference) == b"{}"
    with pytest.raises(ValueError, match="traverse"):
        store.put_bytes("../escape", b"bad")


def test_s3_object_store_round_trip():
    client = FakeS3Client()
    store = S3ObjectStore(bucket="bucket", prefix="prefix", client=client)
    reference = store.put_bytes("simulations/example.npz", b"draws")
    assert reference == "s3://bucket/prefix/simulations/example.npz"
    assert store.exists(reference)
    assert store.get_bytes(reference) == b"draws"
    assert not store.exists("s3://bucket/prefix/missing")


def test_local_json_state_store_round_trip(tmp_path):
    store = LocalJsonStateStore(tmp_path)
    reference = store.write("publisher/latest", {"status": "PASS"})
    assert Path(reference).exists()
    assert store.read("publisher/latest") == {"status": "PASS"}


def test_local_factories_preserve_existing_store_types(tmp_path):
    settings = StorageSettings()
    assert isinstance(
        create_market_quote_store(tmp_path / "markets", settings=settings),
        LocalMarketQuoteStore,
    )
    assert isinstance(
        create_simulation_snapshot_store(tmp_path / "simulations", settings=settings),
        LocalSimulationSnapshotStore,
    )


def test_packaged_storage_migration_is_discoverable():
    assert "0001_platform_storage.sql" in migration_names()


def test_postgres_state_store_round_trip_with_injected_connection():
    database = FakeDatabase()
    store = PostgresJsonStateStore(
        "postgresql://test", connect=database.connect
    )
    reference = store.write("publisher/latest", {"status": "PASS"})
    assert reference.endswith("publisher/latest")
    assert store.read("publisher/latest") == {"status": "PASS"}


def test_postgres_market_history_round_trip_with_injected_connection():
    database = FakeDatabase()
    store = PostgresMarketQuoteStore(
        "postgresql://test", connect=database.connect
    )
    quote = MarketQuote(
        game_pk=99,
        sportsbook="Book",
        market_type="moneyline",
        selection="ATL",
        american_odds=120,
        captured_at=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        source="manual",
        event_date="2026-08-02",
    )
    assert store.save_many([quote]) is not None
    latest = store.latest("2026-08-02")
    assert len(latest) == 1
    assert latest[0].american_odds == 120


def test_postgres_simulation_metadata_and_object_store_round_trip(tmp_path):
    database = FakeDatabase()
    store = PostgresSimulationSnapshotStore(
        "postgresql://test",
        object_store=LocalObjectStore(tmp_path / "objects"),
        connect=database.connect,
    )
    snapshot = _snapshot()
    manifest_ref, arrays_ref = store.save(snapshot)
    assert manifest_ref.endswith(snapshot.snapshot_id)
    assert arrays_ref.startswith("file://")
    loaded = store.load(manifest_ref)
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert np.array_equal(loaded.away_runs, snapshot.away_runs)
    assert store.latest(99).snapshot_id == snapshot.snapshot_id
    listed = store.list_latest(event_date="2026-08-02")
    assert [item.snapshot_id for item in listed] == [snapshot.snapshot_id]


def test_postgres_advisory_lock_rejects_overlap():
    database = FakeDatabase()
    with postgres_advisory_lock(
        "postgresql://test", lock_name="publisher", connect=database.connect
    ):
        with pytest.raises(RuntimeError, match="already running"):
            with postgres_advisory_lock(
                "postgresql://test", lock_name="publisher", connect=database.connect
            ):
                raise AssertionError("lock should not be acquired")
    assert database.locked is False
