from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

import numpy as np
import pandas as pd

from .starter_features import parse_innings_pitched

PITCHING_CONTEXT_SCHEMA_VERSION = 1
PITCHING_CONTEXT_FEATURES: tuple[str, ...] = (
    "starter_fip",
    "starter_k_minus_bb",
    "bullpen_xfip",
    "bullpen_fatigue",
    "closer_available",
)


class PitchingContextError(RuntimeError):
    """Raised when historical pitching context cannot be built without leakage."""


class PitchingContextClient(Protocol):
    def completed_schedule_range(self, start_date: str, end_date: str) -> dict[str, Any]: ...
    def live_feed(self, game_pk: int) -> dict[str, Any]: ...


@dataclass
class PitcherState:
    outs: int = 0
    strikeouts: float = 0.0
    walks: float = 0.0
    hit_batters: float = 0.0
    home_runs: float = 0.0
    batters_faced: float = 0.0
    starts: int = 0
    last_start_date: date | None = None
    recent_pitches: deque[float] = field(default_factory=lambda: deque(maxlen=3))

    def snapshot(self) -> dict[str, float | None]:
        innings = self.outs / 3.0
        # Conservative priors prevent first-start extremes while retaining point-in-time order.
        prior_innings = 20.0
        prior_fip = 4.20
        prior_batters = 85.0
        prior_kbb = 10.0
        numerator = (
            13.0 * self.home_runs
            + 3.0 * (self.walks + self.hit_batters)
            - 2.0 * self.strikeouts
        )
        prior_numerator = (prior_fip - 3.10) * prior_innings
        fip = (numerator + prior_numerator) / (innings + prior_innings) + 3.10
        kbb = 100.0 * (
            self.strikeouts - self.walks + prior_batters * prior_kbb / 100.0
        ) / (self.batters_faced + prior_batters)
        average_recent_pitches = (
            float(np.mean(self.recent_pitches)) if self.recent_pitches else None
        )
        return {
            "starter_fip": float(fip),
            "starter_k_minus_bb": float(kbb),
            "starter_recent_pitches": average_recent_pitches,
            "starter_starts_observed": float(self.starts),
        }


@dataclass
class RelieverState:
    cumulative_outs: int = 0
    strikeouts: float = 0.0
    walks: float = 0.0
    hit_batters: float = 0.0
    home_runs: float = 0.0
    saves: float = 0.0
    games_finished: float = 0.0
    appearances: list[tuple[date, float, int]] = field(default_factory=list)


@dataclass
class TeamBullpenState:
    relievers: dict[int, RelieverState] = field(default_factory=dict)

    def snapshot(self, game_date: date) -> dict[str, float]:
        total_outs = 0
        strikeouts = walks = hit_batters = home_runs = 0.0
        weighted_pitches = 0.0
        for reliever in self.relievers.values():
            total_outs += reliever.cumulative_outs
            strikeouts += reliever.strikeouts
            walks += reliever.walks
            hit_batters += reliever.hit_batters
            home_runs += reliever.home_runs
            for appearance_date, pitches, _outs in reliever.appearances:
                days = (game_date - appearance_date).days
                if days == 1:
                    weighted_pitches += pitches
                elif days == 2:
                    weighted_pitches += 0.60 * pitches
                elif days == 3:
                    weighted_pitches += 0.30 * pitches

        innings = total_outs / 3.0
        prior_innings = 60.0
        prior_fip = 4.20
        numerator = 13.0 * home_runs + 3.0 * (walks + hit_batters) - 2.0 * strikeouts
        prior_numerator = (prior_fip - 3.10) * prior_innings
        bullpen_fip = (numerator + prior_numerator) / (innings + prior_innings) + 3.10
        fatigue = float(np.clip(weighted_pitches / 110.0, 0.0, 1.5))

        closer_available = 1.0
        if self.relievers:
            closer_id, closer = max(
                self.relievers.items(),
                key=lambda item: (3.0 * item[1].saves + item[1].games_finished, item[0]),
            )
            del closer_id
            last1 = sum(
                pitches for appearance_date, pitches, _ in closer.appearances
                if (game_date - appearance_date).days == 1
            )
            last2 = sum(
                pitches for appearance_date, pitches, _ in closer.appearances
                if 1 <= (game_date - appearance_date).days <= 2
            )
            if last1 >= 25.0 or last2 >= 45.0:
                closer_available = 0.0
            elif last1 >= 15.0 or last2 >= 35.0:
                closer_available = 0.5

        return {
            "bullpen_xfip": float(bullpen_fip),
            "bullpen_fatigue": fatigue,
            "closer_available": closer_available,
        }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pitching_stats(player: Mapping[str, Any]) -> Mapping[str, Any]:
    return ((player.get("stats") or {}).get("pitching") or {})


def _player_id(player: Mapping[str, Any], key: str) -> int:
    person = player.get("person") or {}
    value = person.get("id")
    if value is None:
        value = str(key).removeprefix("ID")
    return int(value)


def _outs(stats: Mapping[str, Any]) -> int:
    innings = parse_innings_pitched(stats.get("inningsPitched"))
    return int(round((innings or 0.0) * 3.0))


def _side_payload(feed: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    return (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}).get(side) or {}


def _team_abbreviation(feed: Mapping[str, Any], side: str) -> str:
    game_data = feed.get("gameData") or {}
    team = ((game_data.get("teams") or {}).get(side) or {})
    abbreviation = team.get("abbreviation")
    if not abbreviation:
        raise PitchingContextError(f"Live feed is missing {side} team abbreviation")
    return str(abbreviation)


def _official_date(feed: Mapping[str, Any]) -> date:
    game_data = feed.get("gameData") or {}
    value = ((game_data.get("datetime") or {}).get("officialDate"))
    if not value:
        raise PitchingContextError("Live feed is missing officialDate")
    return pd.Timestamp(value).date()


def _game_pk(feed: Mapping[str, Any]) -> int:
    game_data = feed.get("gameData") or {}
    game = game_data.get("game") or {}
    value = game.get("pk") or feed.get("gamePk")
    if value is None:
        raise PitchingContextError("Live feed is missing gamePk")
    return int(value)


def _extract_team_pitching(feed: Mapping[str, Any], side: str) -> dict[str, Any]:
    block = _side_payload(feed, side)
    players = block.get("players") or {}
    pitcher_order = [int(value) for value in (block.get("pitchers") or [])]
    if not pitcher_order:
        # Some finalized GUMBO feeds omit the team-level pitcher-order array while
        # retaining each pitcher's game line under ``players``. Recover only players
        # with evidence of an actual pitching appearance. A scheduled/postponed game
        # has no such lines and still fails closed.
        recovered: list[tuple[int, bool, int]] = []
        for key, player in players.items():
            stats = _pitching_stats(player)
            outs = _outs(stats)
            pitches = int(
                _float(stats.get("numberOfPitches"), _float(stats.get("pitchesThrown")))
            )
            batters = int(_float(stats.get("battersFaced")))
            started = int(_float(stats.get("gamesStarted"))) > 0
            if outs > 0 or pitches > 0 or batters > 0 or started:
                recovered.append((_player_id(player, str(key)), started, outs))
        recovered.sort(key=lambda item: (not item[1], -item[2], item[0]))
        pitcher_order = [pitcher_id for pitcher_id, _started, _outs_value in recovered]
    if not pitcher_order:
        raise PitchingContextError(f"Game {_game_pk(feed)} has no {side} pitchers")
    parsed: list[dict[str, Any]] = []
    for order, pitcher_id in enumerate(pitcher_order):
        player = players.get(f"ID{pitcher_id}") or players.get(str(pitcher_id)) or {}
        stats = _pitching_stats(player)
        parsed.append(
            {
                "pitcher_id": _player_id(player, f"ID{pitcher_id}"),
                "is_starter": order == 0 or int(_float(stats.get("gamesStarted"))) > 0,
                "outs": _outs(stats),
                "pitches": _float(stats.get("numberOfPitches"), _float(stats.get("pitchesThrown"))),
                "strikeouts": _float(stats.get("strikeOuts")),
                "walks": _float(stats.get("baseOnBalls")),
                "hit_batters": _float(stats.get("hitBatsmen")),
                "home_runs": _float(stats.get("homeRuns")),
                "batters_faced": _float(stats.get("battersFaced")),
                "saves": _float(stats.get("saves")),
                "games_finished": _float(stats.get("gamesFinished")),
            }
        )
    return {
        "team": _team_abbreviation(feed, side),
        "starter": parsed[0],
        "relievers": parsed[1:],
    }


def _snapshot_difference(team_a: Mapping[str, float], team_b: Mapping[str, float], key: str) -> float:
    return float(team_a[key]) - float(team_b[key])


def build_pitching_context_rows(feeds: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Build point-in-time starter/bullpen features from final game feeds.

    All games on the same official date are snapshotted before any of that date's games
    update state. This conservative rule avoids using Game 1 outcomes for a Game 2 line
    that may have been captured before the opener ended.
    """

    parsed_games: list[dict[str, Any]] = []
    seen: set[int] = set()
    for feed in feeds:
        game_pk = _game_pk(feed)
        if game_pk in seen:
            continue
        seen.add(game_pk)
        parsed_games.append(
            {
                "date": _official_date(feed),
                "game_pk": game_pk,
                "away": _extract_team_pitching(feed, "away"),
                "home": _extract_team_pitching(feed, "home"),
            }
        )
    parsed_games.sort(key=lambda item: (item["date"], item["game_pk"]))

    pitcher_states: dict[int, PitcherState] = defaultdict(PitcherState)
    bullpen_states: dict[str, TeamBullpenState] = defaultdict(TeamBullpenState)
    rows: list[dict[str, Any]] = []

    for game_date, day_games in _group_by_date(parsed_games):
        pending: list[dict[str, Any]] = []
        for game in day_games:
            away = game["away"]
            home = game["home"]
            team_a, team_b = sorted((away["team"], home["team"]))
            by_team = {away["team"]: away, home["team"]: home}
            a_side = by_team[team_a]
            b_side = by_team[team_b]
            a_starter = pitcher_states[int(a_side["starter"]["pitcher_id"])].snapshot()
            b_starter = pitcher_states[int(b_side["starter"]["pitcher_id"])].snapshot()
            a_bullpen = bullpen_states[team_a].snapshot(game_date)
            b_bullpen = bullpen_states[team_b].snapshot(game_date)
            rows.append(
                {
                    "schema_version": PITCHING_CONTEXT_SCHEMA_VERSION,
                    "date": pd.Timestamp(game_date),
                    "game_pk": int(game["game_pk"]),
                    "team_a": team_a,
                    "team_b": team_b,
                    "starter_fip_diff": _snapshot_difference(a_starter, b_starter, "starter_fip"),
                    "starter_k_minus_bb_diff": _snapshot_difference(
                        a_starter, b_starter, "starter_k_minus_bb"
                    ),
                    "bullpen_xfip_diff": _snapshot_difference(
                        a_bullpen, b_bullpen, "bullpen_xfip"
                    ),
                    "bullpen_fatigue_diff": _snapshot_difference(
                        a_bullpen, b_bullpen, "bullpen_fatigue"
                    ),
                    "closer_available_diff": _snapshot_difference(
                        a_bullpen, b_bullpen, "closer_available"
                    ),
                    "source": "mlb_stats_api:v1.1/game/feed/live:point_in_time_pitching_backfill",
                }
            )
            pending.append(game)
        for game in pending:
            _apply_game_update(game, pitcher_states, bullpen_states)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["date", "game_pk"]).reset_index(drop=True)
    return frame


def _group_by_date(games: list[dict[str, Any]]) -> Iterable[tuple[date, list[dict[str, Any]]]]:
    current: date | None = None
    bucket: list[dict[str, Any]] = []
    for game in games:
        game_date = game["date"]
        if current is not None and game_date != current:
            yield current, bucket
            bucket = []
        current = game_date
        bucket.append(game)
    if current is not None:
        yield current, bucket


def _apply_game_update(
    game: Mapping[str, Any],
    pitcher_states: dict[int, PitcherState],
    bullpen_states: dict[str, TeamBullpenState],
) -> None:
    game_date = game["date"]
    for side_name in ("away", "home"):
        side = game[side_name]
        starter = side["starter"]
        state = pitcher_states[int(starter["pitcher_id"])]
        state.outs += int(starter["outs"])
        state.strikeouts += float(starter["strikeouts"])
        state.walks += float(starter["walks"])
        state.hit_batters += float(starter["hit_batters"])
        state.home_runs += float(starter["home_runs"])
        state.batters_faced += float(starter["batters_faced"])
        state.starts += 1
        state.last_start_date = game_date
        state.recent_pitches.append(float(starter["pitches"]))

        bullpen = bullpen_states[str(side["team"])]
        for appearance in side["relievers"]:
            pitcher_id = int(appearance["pitcher_id"])
            reliever = bullpen.relievers.setdefault(pitcher_id, RelieverState())
            reliever.cumulative_outs += int(appearance["outs"])
            reliever.strikeouts += float(appearance["strikeouts"])
            reliever.walks += float(appearance["walks"])
            reliever.hit_batters += float(appearance["hit_batters"])
            reliever.home_runs += float(appearance["home_runs"])
            reliever.saves += float(appearance["saves"])
            reliever.games_finished += float(appearance["games_finished"])
            reliever.appearances.append(
                (game_date, float(appearance["pitches"]), int(appearance["outs"]))
            )
            reliever.appearances = [
                item for item in reliever.appearances if (game_date - item[0]).days <= 7
            ]


def schedule_game_pks(payload: Mapping[str, Any]) -> list[int]:
    """Return games that were actually completed, not merely abstract-final records.

    MLB can label postponed, cancelled, or rescheduled placeholders with an abstract
    game state of ``Final`` even though no pitches were thrown. The detailed/coded
    state is authoritative for the pitching backfill because a non-played placeholder
    has no pitcher lines to ingest.
    """

    game_pks: list[int] = []
    for block in payload.get("dates", []) or []:
        for game in block.get("games", []) or []:
            status = game.get("status") or {}
            detailed = str(status.get("detailedState") or "").strip().lower()
            coded = str(
                status.get("codedGameState") or status.get("statusCode") or ""
            ).strip().upper()
            completed = (
                detailed.startswith("final")
                or detailed in {"game over", "completed early"}
                or coded in {"F", "O"}
            )
            non_played = any(
                token in detailed
                for token in ("postpon", "cancel", "suspend", "resched", "scheduled")
            )
            if completed and not non_played:
                game_pks.append(int(game["gamePk"]))
    return sorted(set(game_pks))


def _read_cached_feed(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_cached_feed(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def fetch_pitching_context(
    client: PitchingContextClient,
    *,
    start_date: str,
    end_date: str,
    cache_dir: str | Path | None = None,
    progress_callback: Callable[[int, int, int, str], None] | None = None,
) -> pd.DataFrame:
    schedule = client.completed_schedule_range(start_date, end_date)
    game_pks = schedule_game_pks(schedule)
    cache_root = Path(cache_dir) if cache_dir is not None else None
    feeds: list[dict[str, Any]] = []
    accepted_game_pks: set[int] = set()
    total = len(game_pks)
    requested_start = pd.Timestamp(start_date).date()
    requested_end = pd.Timestamp(end_date).date()
    for index, game_pk in enumerate(game_pks, start=1):
        source = "network"
        feed: dict[str, Any] | None = None
        cache_path = cache_root / f"{game_pk}.json" if cache_root is not None else None
        if cache_path is not None:
            feed = _read_cached_feed(cache_path)
            if feed is not None:
                source = "cache"
        if feed is None:
            feed = client.live_feed(game_pk)
            if cache_path is not None:
                _write_cached_feed(cache_path, feed)

        feed_date = _official_date(feed)
        status = (feed.get("gameData") or {}).get("status") or {}
        detailed = str(status.get("detailedState") or "").strip().lower()
        if not requested_start <= feed_date <= requested_end:
            source = "skipped-out-of-range"
        elif any(token in detailed for token in ("postpon", "cancel", "suspend", "resched")):
            source = "skipped-non-played"
        else:
            feeds.append(feed)
            accepted_game_pks.add(game_pk)
        if progress_callback is not None:
            progress_callback(index, total, game_pk, source)
    frame = build_pitching_context_rows(feeds)
    expected = accepted_game_pks
    observed = set(frame["game_pk"].astype(int)) if not frame.empty else set()
    if observed != expected:
        missing = sorted(expected.difference(observed))
        raise PitchingContextError(f"Pitching backfill omitted games: {missing}")
    return frame


def write_pitching_context(path: str | Path, frame: pd.DataFrame) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(temp, index=False)
    temp.replace(target)
    return target


def audit_pitching_context(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"status": "MISSING", "path": str(target), "rows": 0}
    frame = pd.read_csv(target, parse_dates=["date"])
    required = {
        "date", "game_pk", "team_a", "team_b", "starter_fip_diff",
        "starter_k_minus_bb_diff", "bullpen_xfip_diff", "bullpen_fatigue_diff",
        "closer_available_diff",
    }
    missing = sorted(required.difference(frame.columns))
    duplicate_game_pks = int(frame["game_pk"].duplicated().sum()) if "game_pk" in frame else 0
    feature_coverage = {
        name: float(frame[f"{name}_diff"].notna().mean())
        for name in PITCHING_CONTEXT_FEATURES
        if f"{name}_diff" in frame
    }
    status = "PASS" if not missing and duplicate_game_pks == 0 and len(frame) else "FAIL"
    return {
        "status": status,
        "path": str(target),
        "rows": int(len(frame)),
        "date_min": frame["date"].min().date().isoformat() if len(frame) else None,
        "date_max": frame["date"].max().date().isoformat() if len(frame) else None,
        "missing_columns": missing,
        "duplicate_game_pks": duplicate_game_pks,
        "feature_coverage": feature_coverage,
    }
