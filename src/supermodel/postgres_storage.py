from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
from importlib import resources
import io
import json
from typing import Any, Callable, Iterable, Iterator

import numpy as np

from .market_schema import MarketQuote, QuoteSource
from .simulation_store import SimulationSnapshot
from .storage import ObjectStore


ConnectFactory = Callable[[str], Any]


def _default_connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PostgreSQL storage requires the 'storage' optional dependencies"
        ) from exc
    return psycopg.connect(dsn)


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _quote_id(quote: MarketQuote) -> str:
    return sha256(_canonical_json(quote.to_record()).encode("utf-8")).hexdigest()


def _line_key(value: float | None) -> str:
    return "" if value is None else format(float(value), ".8g")


def _team_key(value: str | None) -> str:
    return str(value or "")


def migration_names() -> tuple[str, ...]:
    root = resources.files("supermodel.storage_migrations")
    return tuple(
        sorted(
            item.name
            for item in root.iterdir()
            if item.name.endswith(".sql") and item.name[:4].isdigit()
        )
    )


def apply_migrations(
    dsn: str,
    *,
    connect: ConnectFactory | None = None,
) -> tuple[str, ...]:
    """Apply packaged PostgreSQL migrations exactly once."""

    connector = connect or _default_connect
    applied: list[str] = []
    connection = connector(dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS supermodel")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS supermodel.schema_migrations (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        connection.commit()
        root = resources.files("supermodel.storage_migrations")
        for name in migration_names():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM supermodel.schema_migrations WHERE version = %s",
                    (name,),
                )
                if cursor.fetchone() is not None:
                    continue
                sql = root.joinpath(name).read_text(encoding="utf-8")
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO supermodel.schema_migrations (version) VALUES (%s)",
                    (name,),
                )
            connection.commit()
            applied.append(name)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return tuple(applied)


def postgres_healthcheck(
    dsn: str,
    *,
    connect: ConnectFactory | None = None,
) -> dict[str, Any]:
    connector = connect or _default_connect
    connection = connector(dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, now()")
            database, user, checked_at = cursor.fetchone()
            cursor.execute(
                """
                SELECT to_regclass('supermodel.schema_migrations'),
                       to_regclass('supermodel.simulation_snapshots'),
                       to_regclass('supermodel.market_quote_history')
                """
            )
            tables = cursor.fetchone()
        return {
            "status": "PASS",
            "database": database,
            "user": user,
            "checked_at": str(checked_at),
            "migrations_table": tables[0],
            "simulation_table": tables[1],
            "market_table": tables[2],
        }
    finally:
        connection.close()


class PostgresJsonStateStore:
    def __init__(
        self,
        dsn: str,
        *,
        connect: ConnectFactory | None = None,
    ) -> None:
        self.dsn = dsn
        self.connect = connect or _default_connect

    def write(self, key: str, payload: dict[str, Any]) -> str:
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO supermodel.platform_state (state_key, payload, updated_at)
                    VALUES (%s, %s::jsonb, now())
                    ON CONFLICT (state_key) DO UPDATE
                    SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (str(key), _canonical_json(payload)),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return f"postgresql://supermodel/platform_state/{key}"

    def read(self, key: str) -> dict[str, Any] | None:
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload FROM supermodel.platform_state WHERE state_key = %s",
                    (str(key),),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            payload = _json_value(row[0])
            if not isinstance(payload, dict):
                raise ValueError(f"state document {key!r} must be a JSON object")
            return payload
        finally:
            connection.close()


@contextmanager
def postgres_advisory_lock(
    dsn: str,
    *,
    lock_name: str,
    connect: ConnectFactory | None = None,
) -> Iterator[None]:
    """Acquire a connection-scoped PostgreSQL advisory lock.

    This prevents overlapping publisher workers across separate containers or hosts.
    """

    connector = connect or _default_connect
    connection = connector(dsn)
    acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (lock_name,))
            row = cursor.fetchone()
            acquired = bool(row and row[0])
        if not acquired:
            raise RuntimeError(
                f"Slate publisher is already running; PostgreSQL lock {lock_name!r} is held"
            )
        yield
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_name,))
                connection.commit()
            except Exception:
                connection.rollback()
        connection.close()


class PostgresMarketQuoteStore:
    """Shared append-only quote history plus transactional current snapshots."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: ConnectFactory | None = None,
    ) -> None:
        self.dsn = dsn
        self.connect = connect or _default_connect

    @staticmethod
    def _insert_history(cursor: Any, quotes: Iterable[MarketQuote]) -> None:
        for quote in quotes:
            payload = quote.to_record()
            cursor.execute(
                """
                INSERT INTO supermodel.market_quote_history (
                    quote_id, event_date, game_pk, sportsbook, market_type,
                    selection, line, team, american_odds, captured_at,
                    source, provider, payload
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (quote_id) DO NOTHING
                """,
                (
                    _quote_id(quote),
                    quote.event_date,
                    int(quote.game_pk),
                    quote.sportsbook,
                    str(quote.market_type),
                    quote.selection,
                    quote.line,
                    quote.team,
                    int(quote.american_odds),
                    quote.captured_at,
                    str(quote.source),
                    quote.provider,
                    _canonical_json(payload),
                ),
            )

    def save_many(self, quotes: Iterable[MarketQuote]) -> str | None:
        quote_list = list(quotes)
        if not quote_list:
            return None
        event_dates = {quote.event_date for quote in quote_list}
        if None in event_dates or len(event_dates) != 1:
            raise ValueError("all stored quotes must share one non-empty event_date")
        event_date = str(next(iter(event_dates)))
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                self._insert_history(cursor, quote_list)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return f"postgresql://supermodel/market_quote_history/{event_date}"

    def _current_for_book(
        self,
        cursor: Any,
        *,
        event_date: str,
        provider: str,
        sportsbook: str,
    ) -> list[MarketQuote]:
        cursor.execute(
            """
            SELECT payload
            FROM supermodel.current_market_quotes
            WHERE event_date = %s AND provider = %s AND sportsbook_key = %s
            """,
            (event_date, provider, sportsbook.casefold()),
        )
        return [MarketQuote.from_record(_json_value(row[0])) for row in cursor.fetchall()]

    def save_provider_snapshot(
        self,
        quotes: Iterable[MarketQuote],
        *,
        event_date: str,
        provider: str,
        captured_at: datetime,
        expected_sportsbooks: Iterable[str] = (),
        replace_game_pks: Iterable[int] | None = None,
    ) -> int:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        quote_list = list(quotes)
        if any(quote.event_date != event_date for quote in quote_list):
            raise ValueError("provider snapshot quotes must match event_date")
        if any(quote.source is not QuoteSource.PROVIDER for quote in quote_list):
            raise ValueError("provider snapshots may contain provider quotes only")

        by_book: dict[str, list[MarketQuote]] = {}
        for quote in quote_list:
            by_book.setdefault(quote.sportsbook, []).append(quote)
        all_books = {
            str(book).strip() for book in expected_sportsbooks if str(book).strip()
        }
        all_books.update(by_book)
        replace_games = (
            {int(game_pk) for game_pk in replace_game_pks}
            if replace_game_pks is not None
            else None
        )
        changed: list[MarketQuote] = []
        active_changes = 0
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                for sportsbook in sorted(all_books):
                    cursor.execute(
                        """
                        INSERT INTO supermodel.provider_market_snapshots (
                            provider, event_date, sportsbook_key, sportsbook, captured_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (provider, event_date, sportsbook_key) DO UPDATE
                        SET sportsbook = EXCLUDED.sportsbook,
                            captured_at = EXCLUDED.captured_at
                        """,
                        (
                            provider,
                            event_date,
                            sportsbook.casefold(),
                            sportsbook,
                            captured_at.astimezone(timezone.utc),
                        ),
                    )
                    previous_quotes = self._current_for_book(
                        cursor,
                        event_date=event_date,
                        provider=provider,
                        sportsbook=sportsbook,
                    )
                    previous = {quote.quote_key: quote for quote in previous_quotes}
                    incoming = by_book.get(sportsbook, [])
                    incoming_by_key = {quote.quote_key: quote for quote in incoming}
                    previous_replaced = {
                        key: quote
                        for key, quote in previous.items()
                        if replace_games is None or quote.game_pk in replace_games
                    }
                    for key in set(previous_replaced) | set(incoming_by_key):
                        old = previous_replaced.get(key)
                        new = incoming_by_key.get(key)
                        if (
                            old is None
                            or new is None
                            or old.american_odds != new.american_odds
                        ):
                            active_changes += 1
                    preserved = (
                        [
                            quote
                            for quote in previous.values()
                            if replace_games is not None
                            and quote.game_pk not in replace_games
                        ]
                        if replace_games is not None
                        else []
                    )
                    active = [*preserved, *incoming]
                    for quote in active:
                        old = previous.get(quote.quote_key)
                        if old is None or old.american_odds != quote.american_odds:
                            changed.append(quote)

                    cursor.execute(
                        """
                        DELETE FROM supermodel.current_market_quotes
                        WHERE event_date = %s AND provider = %s AND sportsbook_key = %s
                        """,
                        (event_date, provider, sportsbook.casefold()),
                    )
                    for quote in active:
                        cursor.execute(
                            """
                            INSERT INTO supermodel.current_market_quotes (
                                provider, event_date, sportsbook_key, game_pk,
                                market_type, selection, line_key, team_key,
                                captured_at, payload
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                            )
                            ON CONFLICT (
                                provider, event_date, sportsbook_key, game_pk,
                                market_type, selection, line_key, team_key
                            ) DO UPDATE SET
                                captured_at = EXCLUDED.captured_at,
                                payload = EXCLUDED.payload
                            """,
                            (
                                provider,
                                event_date,
                                sportsbook.casefold(),
                                int(quote.game_pk),
                                str(quote.market_type),
                                quote.selection,
                                _line_key(quote.line),
                                _team_key(quote.team),
                                quote.captured_at,
                                _canonical_json(quote.to_record()),
                            ),
                        )
                self._insert_history(cursor, changed)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return active_changes

    def read(self, event_date: str) -> list[MarketQuote]:
        date.fromisoformat(str(event_date))
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload
                    FROM supermodel.market_quote_history
                    WHERE event_date = %s
                    ORDER BY captured_at, quote_id
                    """,
                    (event_date,),
                )
                rows = cursor.fetchall()
            return [MarketQuote.from_record(_json_value(row[0])) for row in rows]
        finally:
            connection.close()

    def current_provider_quotes(
        self, event_date: str
    ) -> tuple[list[MarketQuote], set[str]]:
        date.fromisoformat(str(event_date))
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload
                    FROM supermodel.current_market_quotes
                    WHERE event_date = %s
                    ORDER BY sportsbook_key, game_pk, market_type, selection
                    """,
                    (event_date,),
                )
                rows = cursor.fetchall()
            quotes = [MarketQuote.from_record(_json_value(row[0])) for row in rows]
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sportsbook_key
                    FROM supermodel.provider_market_snapshots
                    WHERE event_date = %s
                    """,
                    (event_date,),
                )
                snapshot_rows = cursor.fetchall()
            represented = {str(row[0]).casefold() for row in snapshot_rows}
            return quotes, represented
        finally:
            connection.close()

    def latest(
        self, event_date: str, *, sportsbook: str | None = None
    ) -> list[MarketQuote]:
        current_provider, represented_books = self.current_provider_quotes(event_date)
        candidates = list(current_provider)
        for quote in self.read(event_date):
            if (
                quote.source is QuoteSource.PROVIDER
                and quote.sportsbook.casefold() in represented_books
            ):
                continue
            candidates.append(quote)
        selected: dict[tuple, MarketQuote] = {}
        target = sportsbook.casefold() if sportsbook else None
        for quote in candidates:
            if target is not None and quote.sportsbook.casefold() != target:
                continue
            current = selected.get(quote.quote_key)
            if current is None or str(quote.captured_at) > str(current.captured_at):
                selected[quote.quote_key] = quote
        return sorted(
            selected.values(),
            key=lambda quote: (
                quote.game_pk,
                quote.sportsbook.casefold(),
                str(quote.market_type),
                quote.selection,
                quote.line if quote.line is not None else -999.0,
                quote.team or "",
            ),
        )

    def sportsbooks(self, event_date: str) -> list[str]:
        return sorted({quote.sportsbook for quote in self.latest(event_date)})


class PostgresSimulationSnapshotStore:
    """PostgreSQL metadata plus object-storage score draws."""

    def __init__(
        self,
        dsn: str,
        *,
        object_store: ObjectStore,
        connect: ConnectFactory | None = None,
    ) -> None:
        self.dsn = dsn
        self.object_store = object_store
        self.connect = connect or _default_connect

    @staticmethod
    def _arrays_bytes(snapshot: SimulationSnapshot) -> bytes:
        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            away_runs=snapshot.away_runs,
            home_runs=snapshot.home_runs,
        )
        return buffer.getvalue()

    def save(self, snapshot: SimulationSnapshot) -> tuple[str, str]:
        object_key = (
            f"simulations/{snapshot.game_pk}/{snapshot.model_track}/"
            f"{snapshot.snapshot_id}.npz"
        )
        arrays_ref = self.object_store.put_bytes(
            object_key,
            self._arrays_bytes(snapshot),
            content_type="application/x-npz",
        )
        manifest = snapshot.manifest()
        manifest["arrays_ref"] = arrays_ref
        event_date = snapshot.metadata.get("game_date")
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO supermodel.simulation_snapshots (
                        snapshot_id, game_pk, event_date, model_track,
                        model_version, git_commit, input_snapshot_hash,
                        created_at, simulations, random_seed,
                        score_draws_sha256, score_draws_object_ref, manifest
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    (
                        snapshot.snapshot_id,
                        int(snapshot.game_pk),
                        event_date,
                        snapshot.model_track,
                        snapshot.model_version,
                        snapshot.git_commit,
                        snapshot.input_snapshot_hash,
                        snapshot.created_at,
                        int(snapshot.simulations),
                        int(snapshot.random_seed),
                        snapshot.score_draws_sha256,
                        arrays_ref,
                        _canonical_json(manifest),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        manifest_ref = (
            "postgresql://supermodel/simulation_snapshots/" + snapshot.snapshot_id
        )
        return manifest_ref, arrays_ref

    def _load_row(self, row: tuple[Any, Any]) -> SimulationSnapshot:
        manifest = _json_value(row[0])
        arrays_ref = str(row[1])
        with np.load(io.BytesIO(self.object_store.get_bytes(arrays_ref))) as arrays:
            away_runs = arrays["away_runs"].copy()
            home_runs = arrays["home_runs"].copy()
        return SimulationSnapshot(
            game_pk=int(manifest["game_pk"]),
            away_team=manifest["away_team"],
            home_team=manifest["home_team"],
            model_track=manifest["model_track"],
            model_version=manifest["model_version"],
            git_commit=manifest["git_commit"],
            input_snapshot_hash=manifest["input_snapshot_hash"],
            created_at=manifest["created_at"],
            random_seed=int(manifest["random_seed"]),
            away_runs=away_runs,
            home_runs=home_runs,
            away_win_probability=manifest.get("away_win_probability"),
            home_win_probability=manifest.get("home_win_probability"),
            component_probabilities=manifest.get("component_probabilities") or {},
            metadata=manifest.get("metadata") or {},
            schema_version=int(manifest.get("schema_version", 1)),
        )

    def load(self, manifest_reference: str) -> SimulationSnapshot:
        snapshot_id = str(manifest_reference).rsplit("/", 1)[-1]
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT manifest, score_draws_object_ref
                    FROM supermodel.simulation_snapshots
                    WHERE snapshot_id = %s
                    """,
                    (snapshot_id,),
                )
                row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError(
                    f"No simulation snapshot exists for snapshot_id {snapshot_id}"
                )
            return self._load_row(row)
        finally:
            connection.close()

    def latest(
        self, game_pk: int, *, model_track: str = "production"
    ) -> SimulationSnapshot | None:
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT manifest, score_draws_object_ref
                    FROM supermodel.simulation_snapshots
                    WHERE game_pk = %s AND model_track = %s
                    ORDER BY created_at DESC, snapshot_id DESC
                    LIMIT 1
                    """,
                    (int(game_pk), str(model_track).lower()),
                )
                row = cursor.fetchone()
            return None if row is None else self._load_row(row)
        finally:
            connection.close()

    def list_latest(
        self,
        *,
        event_date: str | None = None,
        model_track: str = "production",
    ) -> list[SimulationSnapshot]:
        connection = self.connect(self.dsn)
        try:
            with connection.cursor() as cursor:
                if event_date is None:
                    cursor.execute(
                        """
                        SELECT DISTINCT ON (game_pk) manifest, score_draws_object_ref
                        FROM supermodel.simulation_snapshots
                        WHERE model_track = %s
                        ORDER BY game_pk, created_at DESC, snapshot_id DESC
                        """,
                        (str(model_track).lower(),),
                    )
                else:
                    date.fromisoformat(str(event_date))
                    cursor.execute(
                        """
                        SELECT DISTINCT ON (game_pk) manifest, score_draws_object_ref
                        FROM supermodel.simulation_snapshots
                        WHERE model_track = %s AND event_date = %s
                        ORDER BY game_pk, created_at DESC, snapshot_id DESC
                        """,
                        (str(model_track).lower(), event_date),
                    )
                rows = cursor.fetchall()
            snapshots = [self._load_row(row) for row in rows]
            return sorted(snapshots, key=lambda item: (item.created_at, item.game_pk))
        finally:
            connection.close()
