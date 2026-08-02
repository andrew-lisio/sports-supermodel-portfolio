from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .providers import PregameContext


SERIES_CONTEXT_VERSION = "series-context-carryover-v1"
SERIES_CONTEXT_AUTHORITY = "CONTEXT_ONLY_NO_MODEL_PROBABILITY_AUTHORITY"


class SeriesContextError(ValueError):
    """Raised when current-series context cannot be reconstructed safely."""


@dataclass(frozen=True)
class SeriesGameResult:
    date: str
    game_pk: int | None
    away_team: str
    home_team: str
    away_runs: int
    home_runs: int
    winner: str
    loser: str
    margin: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SeriesContext:
    game_pk: int
    slate_date: str
    away_team: str
    home_team: str
    status: str
    games: tuple[SeriesGameResult, ...]
    away_wins: int
    home_wins: int
    away_runs: int
    home_runs: int
    latest_winner: str | None
    latest_loser: str | None
    latest_margin: int | None
    away_consecutive_losses: int
    home_consecutive_losses: int
    summary: str
    version: str = SERIES_CONTEXT_VERSION
    probability_authority: str = SERIES_CONTEXT_AUTHORITY

    @property
    def games_played(self) -> int:
        return len(self.games)

    @property
    def away_run_differential(self) -> int:
        return self.away_runs - self.home_runs

    def to_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "games": [game.to_record() for game in self.games],
            "games_played": self.games_played,
            "away_run_differential": self.away_run_differential,
        }


@dataclass(frozen=True)
class SeriesContextPolicy:
    """Conservative abstention gate for adverse current-series carryover.

    The policy never changes a model probability or flips the model pick. It can only
    prevent a modest-confidence pick from being promoted when multiple independent
    current-series warning signals agree.
    """

    maximum_probability_for_pass: float = 0.57
    minimum_series_games: int = 2
    minimum_series_losses: int = 2
    negative_run_differential_threshold: int = 6
    blowout_margin_runs: int = 5
    bullpen_pitch_disadvantage_threshold: float = 35.0
    high_leverage_pitches_threshold: float = 20.0
    maximum_closer_availability_for_warning: float = 0.35
    minimum_adverse_signals: int = 2
    version: str = SERIES_CONTEXT_VERSION

    def __post_init__(self) -> None:
        if not 0.5 <= self.maximum_probability_for_pass < 1.0:
            raise ValueError("maximum_probability_for_pass must be in [0.5, 1)")
        for name in (
            "minimum_series_games",
            "minimum_series_losses",
            "negative_run_differential_threshold",
            "blowout_margin_runs",
            "minimum_adverse_signals",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.bullpen_pitch_disadvantage_threshold < 0.0:
            raise ValueError("bullpen_pitch_disadvantage_threshold cannot be negative")
        if self.high_leverage_pitches_threshold < 0.0:
            raise ValueError("high_leverage_pitches_threshold cannot be negative")
        if not 0.0 <= self.maximum_closer_availability_for_warning <= 1.0:
            raise ValueError(
                "maximum_closer_availability_for_warning must be in [0, 1]"
            )


def _team_opponent(row: pd.Series, team: str) -> str | None:
    team_a = str(row["team_a"])
    team_b = str(row["team_b"])
    if team_a == team:
        return team_b
    if team_b == team:
        return team_a
    return None


def _game_pk_sort_value(value: Any) -> int:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _game_result(row: pd.Series) -> SeriesGameResult:
    missing_home_away = float(row.get("missing_home_away", 0.0) or 0.0)
    if missing_home_away >= 0.5:
        raise SeriesContextError(
            f"game_pk={row.get('game_pk')} has unresolved home/away identity"
        )
    home_flag = row.get("team_a_is_home")
    if home_flag is None or pd.isna(home_flag):
        raise SeriesContextError(
            f"game_pk={row.get('game_pk')} is missing team_a_is_home"
        )
    team_a = str(row["team_a"])
    team_b = str(row["team_b"])
    a_runs = int(round(float(row["a_runs"])))
    b_runs = int(round(float(row["b_runs"])))
    if float(home_flag) >= 0.5:
        home_team, home_runs = team_a, a_runs
        away_team, away_runs = team_b, b_runs
    else:
        away_team, away_runs = team_a, a_runs
        home_team, home_runs = team_b, b_runs
    winner = away_team if away_runs > home_runs else home_team
    loser = home_team if winner == away_team else away_team
    game_pk_value = row.get("game_pk")
    game_pk = None if game_pk_value is None or pd.isna(game_pk_value) else int(game_pk_value)
    return SeriesGameResult(
        date=pd.Timestamp(row["date"]).date().isoformat(),
        game_pk=game_pk,
        away_team=away_team,
        home_team=home_team,
        away_runs=away_runs,
        home_runs=home_runs,
        winner=winner,
        loser=loser,
        margin=abs(away_runs - home_runs),
    )


def _trailing_matchup_rows(
    games: pd.DataFrame,
    *,
    team: str,
    opponent: str,
    slate_date: pd.Timestamp,
) -> list[pd.Series]:
    prior = games[pd.to_datetime(games["date"]).dt.normalize() < slate_date].copy()
    team_games = prior[(prior["team_a"] == team) | (prior["team_b"] == team)].copy()
    if team_games.empty:
        return []
    team_games["_date"] = pd.to_datetime(team_games["date"]).dt.normalize()
    team_games["_game_pk_sort"] = team_games["game_pk"].map(_game_pk_sort_value)
    team_games = team_games.sort_values(
        ["_date", "_game_pk_sort"], ascending=[False, False]
    )
    trailing: list[pd.Series] = []
    for _, row in team_games.iterrows():
        if _team_opponent(row, team) != opponent:
            break
        trailing.append(row)
    return trailing


def _consecutive_losses(games: Iterable[SeriesGameResult], team: str) -> int:
    losses = 0
    for game in reversed(tuple(games)):
        if game.loser != team:
            break
        losses += 1
    return losses


def _series_summary(
    away_team: str,
    home_team: str,
    away_wins: int,
    home_wins: int,
    away_runs: int,
    home_runs: int,
) -> str:
    if away_wins == home_wins:
        leader = f"Series tied {away_wins}-{home_wins}"
    elif away_wins > home_wins:
        leader = f"{away_team} leads {away_wins}-{home_wins}"
    else:
        leader = f"{home_team} leads {home_wins}-{away_wins}"
    differential = away_runs - home_runs
    if differential == 0:
        run_text = "run differential even"
    elif differential > 0:
        run_text = f"{away_team} +{differential} runs"
    else:
        run_text = f"{home_team} +{abs(differential)} runs"
    return f"{leader}; {run_text}"


def build_series_contexts(
    games: pd.DataFrame,
    contexts: Iterable[PregameContext],
) -> dict[int, SeriesContext]:
    """Reconstruct the active series from each team's trailing schedule.

    A series consists of the consecutive completed games immediately preceding the
    slate in which both clubs faced each other. This prevents an older matchup from a
    prior series from being mixed into the current one, while still supporting off days,
    rescheduled games, and doubleheaders already present in completed history.
    """

    required = {
        "date",
        "game_pk",
        "team_a",
        "team_b",
        "a_runs",
        "b_runs",
        "team_a_is_home",
        "missing_home_away",
    }
    missing = required.difference(games.columns)
    if missing:
        raise SeriesContextError(f"Completed history is missing columns: {sorted(missing)}")

    output: dict[int, SeriesContext] = {}
    for context in contexts:
        if context.game_pk is None:
            raise SeriesContextError("Current-series context requires official game_pk")
        slate_date = pd.Timestamp(context.game_date).normalize()
        away_rows = _trailing_matchup_rows(
            games,
            team=context.away_team,
            opponent=context.home_team,
            slate_date=slate_date,
        )
        home_rows = _trailing_matchup_rows(
            games,
            team=context.home_team,
            opponent=context.away_team,
            slate_date=slate_date,
        )
        # The active series exists only when the matchup is the immediately preceding
        # opponent for both clubs. If either club played someone else more recently, this
        # slate game is a series opener and an older head-to-head must not be reused.
        if not away_rows or not home_rows:
            away_rows = []
            home_rows = []
        away_ids = {
            _game_pk_sort_value(row.get("game_pk"))
            for row in away_rows
        }
        home_ids = {
            _game_pk_sort_value(row.get("game_pk"))
            for row in home_rows
        }
        if away_ids != home_ids:
            raise SeriesContextError(
                f"Inconsistent trailing series history for {context.away_team} at "
                f"{context.home_team}: away_view={sorted(away_ids)}, "
                f"home_view={sorted(home_ids)}"
            )

        chronological_rows = sorted(
            away_rows,
            key=lambda row: (
                pd.Timestamp(row["date"]),
                _game_pk_sort_value(row.get("game_pk")),
            ),
        )
        results = tuple(_game_result(row) for row in chronological_rows)
        away_wins = sum(game.winner == context.away_team for game in results)
        home_wins = sum(game.winner == context.home_team for game in results)
        away_runs = sum(
            game.away_runs if game.away_team == context.away_team else game.home_runs
            for game in results
        )
        home_runs = sum(
            game.away_runs if game.away_team == context.home_team else game.home_runs
            for game in results
        )
        latest = results[-1] if results else None
        if results:
            status = "COMPLETE"
            summary = _series_summary(
                context.away_team,
                context.home_team,
                away_wins,
                home_wins,
                away_runs,
                home_runs,
            )
        else:
            status = "SERIES_OPENER"
            summary = "Series opener; no immediately preceding games between these clubs"
        output[int(context.game_pk)] = SeriesContext(
            game_pk=int(context.game_pk),
            slate_date=context.game_date,
            away_team=context.away_team,
            home_team=context.home_team,
            status=status,
            games=results,
            away_wins=away_wins,
            home_wins=home_wins,
            away_runs=away_runs,
            home_runs=home_runs,
            latest_winner=latest.winner if latest else None,
            latest_loser=latest.loser if latest else None,
            latest_margin=latest.margin if latest else None,
            away_consecutive_losses=_consecutive_losses(results, context.away_team),
            home_consecutive_losses=_consecutive_losses(results, context.home_team),
            summary=summary,
        )
    return output


def _pick_metrics(series: SeriesContext, pick: str) -> tuple[int, int, int, int]:
    if pick == series.away_team:
        wins = series.away_wins
        losses = series.home_wins
        runs = series.away_runs
        opponent_runs = series.home_runs
    elif pick == series.home_team:
        wins = series.home_wins
        losses = series.away_wins
        runs = series.home_runs
        opponent_runs = series.away_runs
    else:
        raise SeriesContextError(
            f"Pick {pick} does not match {series.away_team} or {series.home_team}"
        )
    return wins, losses, runs, opponent_runs


def _bullpen_disadvantage(context: PregameContext, pick: str) -> float | None:
    if pick == context.away_team:
        pick_pitches = context.away_bullpen_recent_pitches
        opponent_pitches = context.home_bullpen_recent_pitches
    elif pick == context.home_team:
        pick_pitches = context.home_bullpen_recent_pitches
        opponent_pitches = context.away_bullpen_recent_pitches
    else:
        return None
    if pick_pitches is None or opponent_pitches is None:
        return None
    return float(pick_pitches) - float(opponent_pitches)


def _pick_bullpen_details(
    context: PregameContext,
    pick: str,
) -> tuple[float | None, float | None, float | None]:
    if pick == context.away_team:
        high_leverage = context.away_bullpen_high_leverage_pitches_yesterday
        closer_available = context.away_closer_available
        appearances = context.away_bullpen_reliever_appearances_weighted
    elif pick == context.home_team:
        high_leverage = context.home_bullpen_high_leverage_pitches_yesterday
        closer_available = context.home_closer_available
        appearances = context.home_bullpen_reliever_appearances_weighted
    else:
        return None, None, None
    return (
        None if high_leverage is None else float(high_leverage),
        None if closer_available is None else float(closer_available),
        None if appearances is None else float(appearances),
    )


def _append_reason(existing: Any, additions: Iterable[str]) -> str:
    reasons = [item for item in str(existing or "").split(";") if item]
    for addition in additions:
        if addition not in reasons:
            reasons.append(addition)
    return ";".join(reasons)


def _rerank(frame: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    result = frame.sort_values(
        ["confidence_score", "pick_probability", "model_overlap"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["confidence_rank"] = np.arange(1, len(result) + 1)
    eligible_index = result.index[result["eligible_for_top_pick"].astype(bool)].tolist()
    selection_rank = pd.Series(pd.NA, index=result.index, dtype="Int64")
    for rank, index in enumerate(eligible_index, start=1):
        selection_rank.loc[index] = rank
    result["selection_rank"] = selection_rank
    result["is_top_pick"] = (
        result["eligible_for_top_pick"].astype(bool)
        & result["selection_rank"].notna()
        & (result["selection_rank"] <= int(top_n))
    )
    return result


def apply_series_context_policy(
    evaluations: pd.DataFrame,
    *,
    series_contexts: Mapping[int, SeriesContext],
    pregame_contexts: Mapping[int, PregameContext],
    top_n: int,
    policy: SeriesContextPolicy | None = None,
) -> pd.DataFrame:
    """Attach series evidence and apply a context-only abstention gate."""

    if evaluations.empty:
        return evaluations.copy()
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    active_policy = policy or SeriesContextPolicy()
    rows: list[dict[str, Any]] = []
    for row in evaluations.to_dict("records"):
        game_pk = int(row["game_pk"])
        if game_pk not in series_contexts:
            raise SeriesContextError(f"Missing series context for game_pk={game_pk}")
        if game_pk not in pregame_contexts:
            raise SeriesContextError(f"Missing pregame context for game_pk={game_pk}")
        series = series_contexts[game_pk]
        pregame = pregame_contexts[game_pk]
        pick = str(row["pick"])
        pick_wins, pick_losses, pick_runs, opponent_runs = _pick_metrics(series, pick)
        pick_run_differential = pick_runs - opponent_runs
        latest_blowout_loss = bool(
            series.latest_loser == pick
            and series.latest_margin is not None
            and series.latest_margin >= active_policy.blowout_margin_runs
        )
        bullpen_disadvantage = _bullpen_disadvantage(pregame, pick)
        (
            pick_high_leverage_pitches,
            pick_closer_available,
            pick_reliever_appearances,
        ) = _pick_bullpen_details(pregame, pick)

        reasons: list[str] = []
        if pick_losses >= active_policy.minimum_series_losses:
            reasons.append("SERIES_TRAILING_MULTIPLE_GAMES")
        if pick_run_differential <= -active_policy.negative_run_differential_threshold:
            reasons.append("SERIES_NEGATIVE_RUN_DIFFERENTIAL")
        if latest_blowout_loss:
            reasons.append("SERIES_LATEST_BLOWOUT_LOSS")
        if (
            bullpen_disadvantage is not None
            and bullpen_disadvantage >= active_policy.bullpen_pitch_disadvantage_threshold
        ):
            reasons.append("BULLPEN_CARRYOVER_DISADVANTAGE")
        if (
            pick_high_leverage_pitches is not None
            and pick_high_leverage_pitches >= active_policy.high_leverage_pitches_threshold
            and pick_closer_available is not None
            and pick_closer_available
            <= active_policy.maximum_closer_availability_for_warning
        ):
            reasons.append("HIGH_LEVERAGE_BULLPEN_USED_YESTERDAY")

        context_conflict = bool(
            series.games_played >= active_policy.minimum_series_games
            and float(row["pick_probability"]) <= active_policy.maximum_probability_for_pass
            and len(reasons) >= active_policy.minimum_adverse_signals
        )
        if context_conflict:
            existing_status = str(row.get("selection_status") or "ELIGIBLE")
            row["selection_status"] = (
                "PASS — SERIES CONTEXT"
                if existing_status == "ELIGIBLE"
                else "PASS — MODEL + SERIES CONTEXT"
            )
            row["selection_reasons"] = _append_reason(row.get("selection_reasons"), reasons)
            row["selection_reason_count"] = len(
                [item for item in str(row["selection_reasons"]).split(";") if item]
            )
            row["eligible_for_top_pick"] = False
            row["is_top_pick"] = False

        row.update(
            {
                "series_context_version": series.version,
                "series_context_probability_authority": series.probability_authority,
                "series_context_status": series.status,
                "series_context_summary": series.summary,
                "series_games_played": series.games_played,
                "series_away_wins": series.away_wins,
                "series_home_wins": series.home_wins,
                "series_away_runs": series.away_runs,
                "series_home_runs": series.home_runs,
                "series_run_differential_away": series.away_run_differential,
                "series_latest_winner": series.latest_winner,
                "series_latest_loser": series.latest_loser,
                "series_latest_margin": series.latest_margin,
                "series_latest_blowout": bool(
                    series.latest_margin is not None
                    and series.latest_margin >= active_policy.blowout_margin_runs
                ),
                "series_away_consecutive_losses": series.away_consecutive_losses,
                "series_home_consecutive_losses": series.home_consecutive_losses,
                "series_previous_results": json.dumps(
                    [game.to_record() for game in series.games],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "series_context_pick": pick,
                "series_context_pick_wins": pick_wins,
                "series_context_pick_losses": pick_losses,
                "series_context_pick_run_differential": pick_run_differential,
                "series_context_bullpen_pitch_disadvantage": bullpen_disadvantage,
                "series_context_pick_high_leverage_pitches_yesterday": (
                    pick_high_leverage_pitches
                ),
                "series_context_pick_closer_available": pick_closer_available,
                "series_context_pick_reliever_appearances_weighted": (
                    pick_reliever_appearances
                ),
                "series_context_conflict": context_conflict,
                "series_context_reasons": ";".join(reasons),
            }
        )
        rows.append(row)
    return _rerank(pd.DataFrame(rows), top_n=top_n)
