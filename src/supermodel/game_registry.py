from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


class ScheduleIntegrityError(ValueError):
    """Raised when an official schedule payload has conflicting game identity."""


@dataclass(frozen=True)
class GameRecord:
    """Canonical official-game identity keyed by MLB ``gamePk``.

    The record intentionally stores identity and pregame schedule fields only. It is
    safe to preserve in an immutable snapshot and can distinguish doubleheaders even
    when the teams and official date are identical.
    """

    game_pk: int
    official_date: str
    game_datetime: str
    game_number: int
    double_header: str
    status_abstract: str
    status_detailed: str
    away_team_id: int
    away_team_name: str
    away_team_abbreviation: str | None
    home_team_id: int
    home_team_name: str
    home_team_abbreviation: str | None
    venue_id: int | None
    venue_name: str | None
    away_probable_pitcher_id: int | None
    away_probable_pitcher_name: str | None
    home_probable_pitcher_id: int | None
    home_probable_pitcher_name: str | None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping or mapping[key] is None:
        raise ScheduleIntegrityError(f"Missing {context}.{key}")
    return mapping[key]


def _team_fields(game: dict[str, Any], side: str) -> tuple[int, str, str | None, int | None, str | None]:
    side_payload = _required(_required(game, "teams", "game"), side, f"game.teams")
    team = _required(side_payload, "team", f"game.teams.{side}")
    team_id = int(_required(team, "id", f"game.teams.{side}.team"))
    team_name = str(_required(team, "name", f"game.teams.{side}.team"))
    abbreviation = team.get("abbreviation")
    pitcher = side_payload.get("probablePitcher") or {}
    pitcher_id = int(pitcher["id"]) if pitcher.get("id") is not None else None
    pitcher_name = str(pitcher["fullName"]) if pitcher.get("fullName") else None
    return team_id, team_name, str(abbreviation) if abbreviation else None, pitcher_id, pitcher_name


def parse_mlb_schedule(payload: dict[str, Any]) -> list[GameRecord]:
    """Parse an MLB Stats API schedule response into canonical game records.

    Duplicate ``gamePk`` values are accepted only when their canonical records are
    identical. Conflicting duplicates are rejected instead of silently selecting one.
    """

    by_game_pk: dict[int, GameRecord] = {}
    for date_block in payload.get("dates", []):
        official_date = str(_required(date_block, "date", "date"))
        for game in date_block.get("games", []):
            game_pk = int(_required(game, "gamePk", "game"))
            game_datetime = str(_required(game, "gameDate", "game"))
            away_id, away_name, away_abbr, away_pitcher_id, away_pitcher_name = _team_fields(game, "away")
            home_id, home_name, home_abbr, home_pitcher_id, home_pitcher_name = _team_fields(game, "home")
            venue = game.get("venue") or {}
            status = game.get("status") or {}
            record = GameRecord(
                game_pk=game_pk,
                official_date=official_date,
                game_datetime=game_datetime,
                game_number=int(game.get("gameNumber") or 1),
                double_header=str(game.get("doubleHeader") or "N"),
                status_abstract=str(status.get("abstractGameState") or "Unknown"),
                status_detailed=str(status.get("detailedState") or "Unknown"),
                away_team_id=away_id,
                away_team_name=away_name,
                away_team_abbreviation=away_abbr,
                home_team_id=home_id,
                home_team_name=home_name,
                home_team_abbreviation=home_abbr,
                venue_id=int(venue["id"]) if venue.get("id") is not None else None,
                venue_name=str(venue["name"]) if venue.get("name") else None,
                away_probable_pitcher_id=away_pitcher_id,
                away_probable_pitcher_name=away_pitcher_name,
                home_probable_pitcher_id=home_pitcher_id,
                home_probable_pitcher_name=home_pitcher_name,
            )
            existing = by_game_pk.get(game_pk)
            if existing is not None and existing != record:
                raise ScheduleIntegrityError(f"Conflicting records for gamePk={game_pk}")
            by_game_pk[game_pk] = record
    return sorted(by_game_pk.values(), key=lambda r: (r.game_datetime, r.game_pk))


def index_by_game_pk(records: Iterable[GameRecord]) -> dict[int, GameRecord]:
    index: dict[int, GameRecord] = {}
    for record in records:
        existing = index.get(record.game_pk)
        if existing is not None and existing != record:
            raise ScheduleIntegrityError(f"Conflicting records for gamePk={record.game_pk}")
        index[record.game_pk] = record
    return index


def _parse_capture_time(captured_at: str | datetime) -> datetime:
    if isinstance(captured_at, datetime):
        dt = captured_at
    else:
        value = captured_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("captured_at must include a timezone offset")
    return dt.astimezone(timezone.utc)


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


class ImmutableSnapshotStore:
    """Content-addressed, append-only storage for point-in-time JSON snapshots."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write(
        self,
        *,
        kind: str,
        captured_at: str | datetime,
        payload: dict[str, Any],
        source: str,
        identity: str,
    ) -> Path:
        capture_time = _parse_capture_time(captured_at)
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "captured_at": capture_time.isoformat().replace("+00:00", "Z"),
            "source": source,
            "identity": identity,
            "payload": payload,
        }
        body = _canonical_bytes(envelope)
        digest = sha256(body).hexdigest()
        safe_kind = kind.replace("/", "_")
        safe_identity = identity.replace("/", "_").replace("\\", "_")
        directory = self.root / safe_kind / capture_time.strftime("%Y/%m/%d") / safe_identity
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{capture_time.strftime('%Y%m%dT%H%M%SZ')}_{digest[:16]}.json"
        path = directory / filename

        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            if path.read_bytes() != body:
                raise FileExistsError(f"Immutable snapshot collision at {path}")
            return path
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def write_pregame(
        self,
        *,
        game_pk: int,
        game_datetime: str | datetime,
        context_payload: dict[str, Any],
        captured_at: str | datetime,
        source: str,
    ) -> Path:
        """Write one immutable pregame feature/context snapshot keyed by ``gamePk``.

        The capture timestamp must not be later than the scheduled game timestamp. This
        makes accidental post-start snapshots fail closed instead of entering a pregame
        training or evaluation set.
        """

        capture_time = _parse_capture_time(captured_at)
        scheduled_time = _parse_capture_time(game_datetime)
        if capture_time > scheduled_time:
            raise ScheduleIntegrityError("Pregame snapshot was captured after game start")
        if int(context_payload.get("game_pk", game_pk)) != game_pk:
            raise ScheduleIntegrityError("Pregame snapshot game_pk does not match identity")
        supplied_game_time = context_payload.get("game_datetime")
        if supplied_game_time is not None and _parse_capture_time(supplied_game_time) != scheduled_time:
            raise ScheduleIntegrityError("Pregame snapshot game_datetime does not match identity")
        payload = dict(context_payload)
        payload["game_pk"] = game_pk
        payload["game_datetime"] = scheduled_time.isoformat().replace("+00:00", "Z")
        return self.write(
            kind="mlb_pregame",
            captured_at=captured_at,
            payload=payload,
            source=source,
            identity=str(game_pk),
        )

    def write_schedule(
        self,
        *,
        raw_payload: dict[str, Any],
        captured_at: str | datetime,
        source: str,
    ) -> Path:
        records = parse_mlb_schedule(raw_payload)
        canonical_payload = {
            "records": [record.to_record() for record in records],
            "raw_payload": raw_payload,
            "raw_payload_sha256": sha256(_canonical_bytes(raw_payload)).hexdigest(),
        }
        dates = sorted({record.official_date for record in records})
        identity = dates[0] if len(dates) == 1 else f"{dates[0]}_to_{dates[-1]}" if dates else "empty"
        return self.write(
            kind="mlb_schedule",
            captured_at=captured_at,
            payload=canonical_payload,
            source=source,
            identity=identity,
        )

    @staticmethod
    def read(path: str | Path) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))
