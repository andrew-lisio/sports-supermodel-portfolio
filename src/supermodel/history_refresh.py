from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .game_registry import ImmutableSnapshotStore, ScheduleIntegrityError


class HistoryFreshnessError(ScheduleIntegrityError):
    """Raised when a slate would be evaluated from incomplete recent results."""


class HistoryRefreshClient(Protocol):
    def completed_schedule_range(self, start_date: str, end_date: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HistoryRefreshReport:
    status: str
    base_latest_date: str
    checked_through_date: str
    latest_completed_date: str
    fetched_start_date: str | None
    fetched_end_date: str | None
    backfilled_games: int
    cached_games: int
    cache_path: Path
    state_path: Path
    schedule_snapshot_path: Path | None

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        for key in ("cache_path", "state_path", "schedule_snapshot_path"):
            value = record.get(key)
            record[key] = str(value) if value is not None else None
        return record


_CACHE_COLUMNS = [
    "date",
    "game_pk",
    "team_a",
    "team_b",
    "a_runs",
    "b_runs",
    "a_win",
    "a_starter",
    "b_starter",
    "team_a_is_home",
    "missing_home_away",
    "venue_name",
    "double_header",
    "source",
]


def _parse_date(value: str | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _status_text(game: dict[str, Any]) -> str:
    status = game.get("status") or {}
    return " ".join(
        str(status.get(name) or "")
        for name in ("abstractGameState", "detailedState", "codedGameState")
    ).strip().lower()


def _is_final(game: dict[str, Any]) -> bool:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    detailed = str(status.get("detailedState") or "").lower()
    coded = str(status.get("codedGameState") or "").upper()
    return (
        abstract == "final"
        or detailed.startswith("final")
        or detailed in {"game over", "completed early"}
        or coded in {"F", "O"}
    )


def _is_nonblocking_nonfinal(game: dict[str, Any]) -> bool:
    text = _status_text(game)
    return any(token in text for token in ("postpon", "cancel", "suspend"))


def _team_fields(game: dict[str, Any], side: str) -> tuple[str, float, str]:
    block = (game.get("teams") or {}).get(side) or {}
    team = block.get("team") or {}
    abbreviation = team.get("abbreviation")
    if not abbreviation:
        raise HistoryFreshnessError(
            f"Completed gamePk={game.get('gamePk')} is missing the {side} abbreviation"
        )

    # MLB's schedule response normally exposes the final score at
    # ``teams.<side>.score``. Some finalized games, however, omit that field while
    # still returning the authoritative total under the hydrated linescore. This
    # occurred for gamePk=823519 (PIT 0, NYY 2) and caused the freshness preflight
    # to fail even though the game was complete. Prefer the normal schedule field,
    # then fall back to ``linescore.teams.<side>.runs`` without treating a zero as
    # missing. The run remains fail-closed if neither official location has a score.
    score = block.get("score")
    if score is None:
        linescore_team = (
            (((game.get("linescore") or {}).get("teams") or {}).get(side)) or {}
        )
        score = linescore_team.get("runs")
    if score is None:
        raise HistoryFreshnessError(
            f"Completed gamePk={game.get('gamePk')} is missing the {side} score "
            "in both teams and linescore payloads"
        )

    probable = block.get("probablePitcher") or {}
    starter = probable.get("fullName")
    if not starter:
        starter = f"Unknown:{int(game['gamePk'])}:{side}"
    return str(abbreviation), float(score), str(starter)


def parse_completed_schedule_games(payload: dict[str, Any]) -> tuple[pd.DataFrame, list[int]]:
    """Convert official completed schedule rows into the canonical game format.

    The schedule response is authoritative for identity, final score, home/away, and the
    postgame probable/starting-pitcher label. A unique fail-closed starter placeholder is
    used only when MLB does not provide a pitcher name, preventing unrelated missing
    starters from sharing one rolling state.
    """

    rows: list[dict[str, Any]] = []
    by_game_pk: dict[int, tuple[str, dict[str, Any]]] = {}
    for date_block in payload.get("dates", []):
        block_date = str(date_block.get("date") or "")
        for game in date_block.get("games", []):
            game_pk = int(game["gamePk"])
            existing = by_game_pk.get(game_pk)
            if existing is None or (_is_final(game) and not _is_final(existing[1])):
                by_game_pk[game_pk] = (block_date, game)

    blocking: list[int] = []
    for game_pk, (block_date, game) in sorted(by_game_pk.items()):
        if not _is_final(game):
            if not _is_nonblocking_nonfinal(game):
                blocking.append(game_pk)
            continue

        away, away_runs, away_starter = _team_fields(game, "away")
        home, home_runs, home_starter = _team_fields(game, "home")
        team_a, team_b = sorted((away, home))
        if team_a == away:
            a_runs, b_runs = away_runs, home_runs
            a_starter, b_starter = away_starter, home_starter
            team_a_is_home = 0.0
        else:
            a_runs, b_runs = home_runs, away_runs
            a_starter, b_starter = home_starter, away_starter
            team_a_is_home = 1.0
        venue = game.get("venue") or {}
        rows.append(
            {
                "date": _parse_date(game.get("officialDate") or block_date),
                "game_pk": game_pk,
                "team_a": team_a,
                "team_b": team_b,
                "a_runs": a_runs,
                "b_runs": b_runs,
                "a_win": int(a_runs > b_runs),
                "a_starter": a_starter,
                "b_starter": b_starter,
                "team_a_is_home": team_a_is_home,
                "missing_home_away": 0.0,
                "venue_name": venue.get("name"),
                "double_header": str(game.get("doubleHeader") or "N"),
                "source": "mlb_stats_api_completed_schedule",
            }
        )
    frame = pd.DataFrame(rows, columns=_CACHE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["date", "game_pk"]).reset_index(drop=True)
    return frame, sorted(blocking)


def _load_cache(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=_CACHE_COLUMNS)
    frame = pd.read_csv(path)
    missing = set(_CACHE_COLUMNS).difference(frame.columns)
    if missing:
        raise HistoryFreshnessError(
            f"History cache {path} is missing columns: {sorted(missing)}"
        )
    frame = frame[_CACHE_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["game_pk"] = frame["game_pk"].astype(int)
    return frame


def _load_state(path: Path, base_latest: pd.Timestamp) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "checked_through_date": base_latest.date().isoformat()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryFreshnessError(f"Could not read history refresh state {path}: {exc}") from exc
    checked = payload.get("checked_through_date")
    if not checked:
        raise HistoryFreshnessError(f"History refresh state {path} has no checked_through_date")
    return payload


def _write_cache_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    output = frame[_CACHE_COLUMNS].copy()
    output["date"] = pd.to_datetime(output["date"]).dt.date.astype(str)
    output.to_csv(temporary, index=False)
    temporary.replace(path)


def _write_state_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _merge_cached_games(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if incoming.empty:
        return existing.copy()
    if existing.empty:
        return incoming.sort_values(["date", "game_pk"]).reset_index(drop=True)
    combined = pd.concat([existing, incoming], ignore_index=True)
    conflicts = combined.groupby("game_pk").agg(
        a_scores=("a_runs", "nunique"),
        b_scores=("b_runs", "nunique"),
        team_a_values=("team_a", "nunique"),
        team_b_values=("team_b", "nunique"),
        dates=("date", "nunique"),
    )
    bad = conflicts[
        (conflicts["a_scores"] > 1)
        | (conflicts["b_scores"] > 1)
        | (conflicts["team_a_values"] > 1)
        | (conflicts["team_b_values"] > 1)
        | (conflicts["dates"] > 1)
    ]
    if not bad.empty:
        raise HistoryFreshnessError(
            f"Conflicting completed-game cache records for gamePk={bad.index.astype(int).tolist()}"
        )
    return (
        combined.sort_values(["date", "game_pk"])
        .drop_duplicates("game_pk", keep="last")
        .reset_index(drop=True)
    )


def refresh_completed_history(
    base_games: pd.DataFrame,
    *,
    slate_date: str,
    client: HistoryRefreshClient,
    snapshot_store: ImmutableSnapshotStore,
    captured_at: datetime,
    cache_path: str | Path = "runtime/data/mlb_completed_games.csv",
) -> tuple[pd.DataFrame, HistoryRefreshReport]:
    """Append every newly completed MLB game before the slate, then fail closed if stale.

    The repository CSVs remain the reproducible seed. Newly completed games are stored in
    a local runtime cache and automatically reused on later slates. The cache is refreshed
    only through the day before the requested slate to prevent same-day target leakage.
    """

    if base_games.empty:
        raise HistoryFreshnessError("Base historical games cannot be empty")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    captured_at = captured_at.astimezone(timezone.utc)

    history = base_games.copy()
    history["date"] = pd.to_datetime(history["date"]).dt.normalize()
    base_latest = history["date"].max()
    target_through = _parse_date(slate_date) - pd.Timedelta(days=1)
    if target_through < base_latest:
        raise HistoryFreshnessError(
            f"Slate {slate_date} predates the repository history ending {base_latest.date()}"
        )

    cache = Path(cache_path)
    state_path = cache.with_suffix(".state.json")
    cached = _load_cache(cache)
    state = _load_state(state_path, base_latest)
    checked_through = max(base_latest, _parse_date(state["checked_through_date"]))
    fetch_start = checked_through + pd.Timedelta(days=1)
    schedule_snapshot_path: Path | None = None
    backfilled_games = 0

    if fetch_start <= target_through:
        try:
            payload = client.completed_schedule_range(
                fetch_start.date().isoformat(), target_through.date().isoformat()
            )
        except Exception as exc:  # API/network errors must not silently fall back to stale data.
            raise HistoryFreshnessError(
                "Could not refresh completed MLB results; refusing to evaluate with stale history: "
                f"{exc}"
            ) from exc
        schedule_snapshot_path = snapshot_store.write_schedule(
            raw_payload=payload,
            captured_at=captured_at,
            source="mlb_stats_api:v1/schedule:completed_history_refresh",
        )
        incoming, blocking = parse_completed_schedule_games(payload)
        if blocking:
            raise HistoryFreshnessError(
                "Prior-date MLB games are not final or explicitly postponed/suspended; "
                f"refusing a stale/incomplete run. gamePk={blocking}"
            )
        before = set(cached["game_pk"].astype(int)) if not cached.empty else set()
        cached = _merge_cached_games(cached, incoming)
        after = set(cached["game_pk"].astype(int)) if not cached.empty else set()
        backfilled_games = len(after - before)
        checked_through = target_through
        _write_cache_atomic(cached, cache)
        _write_state_atomic(
            {
                "schema_version": 1,
                "checked_through_date": checked_through.date().isoformat(),
                "updated_at_utc": captured_at.isoformat().replace("+00:00", "Z"),
                "cached_games": int(len(cached)),
            },
            state_path,
        )

    if checked_through < target_through:
        raise HistoryFreshnessError(
            f"History is checked only through {checked_through.date()}, "
            f"but the {slate_date} slate requires {target_through.date()}"
        )

    cached_for_slate = cached[cached["date"] <= target_through].copy()
    merged = pd.concat([history, cached_for_slate], ignore_index=True, sort=False)
    if "game_pk" in merged.columns:
        with_pk = merged[merged["game_pk"].notna()].copy()
        without_pk = merged[merged["game_pk"].isna()].copy()
        with_pk["game_pk"] = with_pk["game_pk"].astype(int)
        with_pk = with_pk.sort_values(["date", "game_pk"]).drop_duplicates("game_pk", keep="last")
        merged = pd.concat([without_pk, with_pk], ignore_index=True, sort=False)
    merged = merged.sort_values(["date", "team_a", "team_b"]).reset_index(drop=True)
    latest_completed = merged["date"].max()

    report = HistoryRefreshReport(
        status="PASS",
        base_latest_date=base_latest.date().isoformat(),
        checked_through_date=checked_through.date().isoformat(),
        latest_completed_date=latest_completed.date().isoformat(),
        fetched_start_date=(
            fetch_start.date().isoformat() if fetch_start <= target_through else None
        ),
        fetched_end_date=(
            target_through.date().isoformat() if fetch_start <= target_through else None
        ),
        backfilled_games=backfilled_games,
        cached_games=int(len(cached)),
        cache_path=cache,
        state_path=state_path,
        schedule_snapshot_path=schedule_snapshot_path,
    )
    return merged, report
