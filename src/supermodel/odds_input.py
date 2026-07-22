from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd

from .providers import PregameContext


class OddsInputError(ValueError):
    """Raised when user-supplied market inputs are incomplete or invalid."""


@dataclass(frozen=True)
class ManualMoneyline:
    """One two-way moneyline matched to an official MLB game.

    Odds are stored internally as American odds regardless of whether the user entered
    American or decimal prices.
    """

    game_date: str
    away_team: str
    home_team: str
    away_odds: int
    home_odds: int
    game_pk: int | None = None


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds greater than 1.0 to American odds."""

    value = float(decimal_odds)
    if not math.isfinite(value) or value <= 1.0:
        raise OddsInputError("Decimal odds must be a finite number greater than 1.0")
    profit = value - 1.0
    if profit >= 1.0:
        return int(round(profit * 100.0))
    return int(round(-100.0 / profit))


def parse_user_odds(value: Any, *, odds_format: str = "american") -> int:
    """Parse common American or decimal odds values into American odds.

    American input accepts values such as ``+125``, ``-145``, ``100``, ``EVEN``,
    ``EV``, or ``PK``. Decimal input accepts values such as ``2.25`` or ``1.67``.
    """

    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise OddsInputError("Odds value is missing")

    normalized_format = str(odds_format or "american").strip().lower()
    text = str(value).strip().upper()
    if not text:
        raise OddsInputError("Odds value is blank")

    if normalized_format in {"american", "us", "moneyline"}:
        if text in {"EV", "EVEN", "PK", "PICK", "PICKEM", "PICK'EM"}:
            return 100
        text = text.replace(",", "")
        try:
            numeric = float(text)
        except ValueError as exc:
            raise OddsInputError(f"Invalid American odds value: {value!r}") from exc
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise OddsInputError(f"American odds must be a whole number: {value!r}")
        parsed = int(numeric)
        if parsed == 0 or abs(parsed) < 100:
            raise OddsInputError(
                f"American odds must be +100 or greater, or -100 or lower: {value!r}"
            )
        return parsed

    if normalized_format in {"decimal", "eu", "european"}:
        text = text.replace(",", ".")
        try:
            return decimal_to_american(float(text))
        except ValueError as exc:
            raise OddsInputError(f"Invalid decimal odds value: {value!r}") from exc

    raise OddsInputError(
        f"Unsupported odds format {odds_format!r}; use 'american' or 'decimal'"
    )


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()


def _enabled(value: Any) -> bool:
    if _is_blank(value):
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "include"}:
        return True
    if text in {"0", "false", "no", "n", "off", "skip", "exclude"}:
        return False
    raise OddsInputError(f"Invalid include/enabled value: {value!r}")


def _records_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("moneylines"), list):
        records = payload["moneylines"]
    else:
        raise OddsInputError(
            "JSON odds input must be a list of records or an object with a 'moneylines' list"
        )
    if not all(isinstance(record, dict) for record in records):
        raise OddsInputError("Every JSON moneyline entry must be an object")
    return records


def _records_from_path(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path).to_dict("records")
    if suffix == ".json":
        return _records_from_json(path)
    raise OddsInputError("Odds input must be a .csv or .json file")


def moneylines_from_records(
    records: Iterable[dict[str, Any]],
    *,
    default_date: str | None = None,
    default_format: str = "american",
) -> list[ManualMoneyline]:
    """Validate records and convert them to canonical moneyline objects.

    Rows with both prices blank are treated as intentionally skipped. A row with only
    one side entered is rejected so the model never computes a no-vig market from an
    incomplete two-way line.
    """

    output: list[ManualMoneyline] = []
    seen_game_pks: set[int] = set()
    seen_matchups: set[tuple[str, str, str]] = set()

    for row_number, record in enumerate(records, start=2):
        include_value = record.get("include", record.get("enabled", True))
        if not _enabled(include_value):
            continue

        away_raw = record.get("away_odds")
        home_raw = record.get("home_odds")
        if _is_blank(away_raw) and _is_blank(home_raw):
            continue
        if _is_blank(away_raw) or _is_blank(home_raw):
            raise OddsInputError(
                f"Row {row_number}: both away_odds and home_odds are required"
            )

        game_date_raw = str(record.get("game_date") or default_date or "").strip()
        away_team = str(record.get("away_team") or "").strip().upper()
        home_team = str(record.get("home_team") or "").strip().upper()
        if not game_date_raw or not away_team or not home_team:
            raise OddsInputError(
                f"Row {row_number}: game_date, away_team, and home_team are required"
            )
        try:
            game_date = pd.Timestamp(game_date_raw).date().isoformat()
        except (TypeError, ValueError) as exc:
            raise OddsInputError(f"Row {row_number}: invalid game_date {game_date_raw!r}") from exc

        odds_format = str(record.get("odds_format") or default_format)
        away_odds = parse_user_odds(away_raw, odds_format=odds_format)
        home_odds = parse_user_odds(home_raw, odds_format=odds_format)

        game_pk_raw = record.get("game_pk")
        game_pk = None
        if not _is_blank(game_pk_raw):
            try:
                numeric_game_pk = float(game_pk_raw)
            except (TypeError, ValueError) as exc:
                raise OddsInputError(
                    f"Row {row_number}: game_pk must be an integer"
                ) from exc
            if not math.isfinite(numeric_game_pk) or not numeric_game_pk.is_integer():
                raise OddsInputError(f"Row {row_number}: game_pk must be an integer")
            game_pk = int(numeric_game_pk)
            if game_pk <= 0:
                raise OddsInputError(f"Row {row_number}: game_pk must be positive")
            if game_pk in seen_game_pks:
                raise OddsInputError(f"Row {row_number}: duplicate game_pk {game_pk}")
            seen_game_pks.add(game_pk)
        else:
            matchup_key = (game_date, away_team, home_team)
            if matchup_key in seen_matchups:
                raise OddsInputError(
                    f"Row {row_number}: duplicate matchup without game_pk; "
                    "doubleheaders require official game_pk values"
                )
            seen_matchups.add(matchup_key)

        output.append(
            ManualMoneyline(
                game_date=game_date,
                away_team=away_team,
                home_team=home_team,
                away_odds=away_odds,
                home_odds=home_odds,
                game_pk=game_pk,
            )
        )

    if not output:
        raise OddsInputError("No complete moneyline rows were supplied")
    return output


def load_moneylines(
    path: str | Path,
    *,
    default_date: str | None = None,
    default_format: str = "american",
) -> list[ManualMoneyline]:
    """Load a CSV or JSON odds file."""

    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Odds input file does not exist: {input_path}")
    return moneylines_from_records(
        _records_from_path(input_path),
        default_date=default_date,
        default_format=default_format,
    )


def moneylines_to_frame(moneylines: Iterable[ManualMoneyline]) -> pd.DataFrame:
    """Convert canonical moneylines to a portable DataFrame."""

    return pd.DataFrame(
        [
            {
                "game_date": line.game_date,
                "game_pk": line.game_pk,
                "away_team": line.away_team,
                "home_team": line.home_team,
                "away_odds": line.away_odds,
                "home_odds": line.home_odds,
                "odds_format": "american",
            }
            for line in moneylines
        ]
    )


def build_moneyline_template(contexts: Iterable[PregameContext]) -> pd.DataFrame:
    """Create an editable odds-entry table from the official captured slate."""

    rows: list[dict[str, Any]] = []
    for context in contexts:
        rows.append(
            {
                "include": True,
                "game_date": context.game_date,
                "game_pk": context.game_pk,
                "game_number": context.game_number,
                "game_datetime_utc": context.game_datetime,
                "away_team": context.away_team,
                "home_team": context.home_team,
                "away_starter": context.away_probable_pitcher_name or "TBD",
                "home_starter": context.home_probable_pitcher_name or "TBD",
                "lineups_confirmed": context.lineups_confirmed,
                "weather": context.weather_condition or "TBD",
                "wind": context.wind_description or "TBD",
                "away_odds": None,
                "home_odds": None,
                "odds_format": "american",
            }
        )
    return pd.DataFrame(rows)


def write_moneyline_template(
    contexts: Iterable[PregameContext],
    path: str | Path,
) -> Path:
    """Write a blank CSV or JSON odds template for an official slate."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = build_moneyline_template(contexts)
    if output_path.suffix.lower() == ".csv":
        frame.to_csv(output_path, index=False)
    elif output_path.suffix.lower() == ".json":
        output_path.write_text(
            json.dumps({"moneylines": frame.to_dict("records")}, indent=2, default=str),
            encoding="utf-8",
        )
    else:
        raise OddsInputError("Template output must end in .csv or .json")
    return output_path


def collect_moneylines_interactively(
    contexts: Iterable[PregameContext],
    *,
    odds_format: str = "american",
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> list[ManualMoneyline]:
    """Prompt for two-way moneylines in a terminal.

    Entering a blank value or ``skip`` for the away side omits that game. The official
    ``game_pk`` is always attached, so doubleheaders remain unambiguous.
    """

    output_fn("\nEnter both sides of each two-way moneyline. Leave the away line blank to skip.")
    output_fn(f"Input format: {odds_format}. Examples: +125 / -145 or 2.25 / 1.67.\n")
    records: list[dict[str, Any]] = []
    for index, context in enumerate(contexts, start=1):
        game_label = f"Game {context.game_number}" if context.game_number else "Game"
        output_fn(
            f"[{index}] {context.away_team} at {context.home_team} — {game_label} "
            f"(gamePk {context.game_pk})\n"
            f"    Starters: {context.away_probable_pitcher_name or 'TBD'} vs "
            f"{context.home_probable_pitcher_name or 'TBD'}"
        )
        away_value = input_fn(f"    {context.away_team} odds (blank/skip to omit): ").strip()
        if not away_value or away_value.lower() in {"skip", "s"}:
            continue
        home_value = input_fn(f"    {context.home_team} odds: ").strip()
        records.append(
            {
                "game_date": context.game_date,
                "game_pk": context.game_pk,
                "away_team": context.away_team,
                "home_team": context.home_team,
                "away_odds": away_value,
                "home_odds": home_value,
                "odds_format": odds_format,
            }
        )
    return moneylines_from_records(records, default_format=odds_format)
