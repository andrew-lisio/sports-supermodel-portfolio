from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .game_registry import ImmutableSnapshotStore, parse_mlb_schedule
from .mlb_v2 import (
    PoissonScoreModel,
    RANDOM_SEED,
    V2Ensemble,
)
from .mlb_v2 import simulate_poisson_score_distribution
from .providers import PregameContext
from .odds_input import ManualMoneyline, load_moneylines
from .market import (
    american_implied_probability,
    american_to_decimal,
    combine_american_odds,
    no_vig_probabilities,
    probability_to_american,
)

@dataclass(frozen=True)
class LiveEvaluationConfig:
    """Configuration for prediction, simulation, and confidence ranking.

    V2.3.2 intentionally contains no bankroll management, stake sizing, or Kelly
    criterion. Market prices are used only to report implied probability, fair odds,
    and model-versus-market edges.
    """

    simulations: int = 100_000
    score_simulation_weight: float = 0.20
    home_field_logit_adjustment: float = 0.0
    top_n: int = 5

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise ValueError("simulations must be positive")
        if not 0.0 <= self.score_simulation_weight <= 1.0:
            raise ValueError("score_simulation_weight must be between 0 and 1")
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")


class MLBStatsHTTPClient:
    """Minimal no-key client for public MLB Stats API endpoints.

    Network responses should be written to ``ImmutableSnapshotStore`` before they are
    used in a real evaluation. Tests use frozen payloads and never require a network.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://statsapi.mlb.com/api",
        timeout_seconds: float = 20.0,
        retries: int = 2,
        user_agent: str = "SportsSuperModel/2.3.2 (+recreational research use)",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.user_agent = user_agent

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.load(response)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"MLB Stats API request failed for {url}: {last_error}") from last_error

    def schedule(self, game_date: str) -> dict[str, Any]:
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "date": game_date,
                "hydrate": "probablePitcher,team,venue",
            },
        )

    def schedule_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "startDate": start_date,
                "endDate": end_date,
                "hydrate": "team,venue",
            },
        )

    def live_feed(self, game_pk: int) -> dict[str, Any]:
        return self._get_json(f"v1.1/game/{int(game_pk)}/feed/live")

    def person_pitching_stats(self, person_id: int, season: int) -> dict[str, Any]:
        return self._get_json(
            f"v1/people/{int(person_id)}/stats",
            {"stats": "season", "group": "pitching", "season": int(season)},
        )

    def recent_team_schedule(self, team_id: int, end_date: str, days: int = 4) -> dict[str, Any]:
        end = datetime.fromisoformat(end_date).date()
        start = end - timedelta(days=days)
        return self._get_json(
            "v1/schedule",
            {
                "sportId": 1,
                "teamId": int(team_id),
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "hydrate": "linescore",
            },
        )


def _first_stat_split(payload: dict[str, Any]) -> dict[str, Any]:
    for block in payload.get("stats", []):
        splits = block.get("splits") or []
        if splits:
            stat = splits[0].get("stat")
            if isinstance(stat, dict):
                return stat
    return {}


def _float_stat(stat: dict[str, Any], key: str) -> float | None:
    value = stat.get(key)
    if value in (None, "", "-.--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_pitcher_season_stats(payload: dict[str, Any]) -> dict[str, float | None]:
    """Parse a public season-pitching response into available V2 context fields."""

    stat = _first_stat_split(payload)
    innings = _float_stat(stat, "inningsPitched")
    strikeouts = _float_stat(stat, "strikeOuts")
    walks = _float_stat(stat, "baseOnBalls")
    hit_batters = _float_stat(stat, "hitBatsmen") or 0.0
    home_runs = _float_stat(stat, "homeRuns")
    batters_faced = _float_stat(stat, "battersFaced")
    era = _float_stat(stat, "era")
    whip = _float_stat(stat, "whip")

    fip = None
    if innings and innings > 0 and None not in (strikeouts, walks, home_runs):
        # A fixed in-season constant is used only as an interpretable proxy. It is
        # preserved in provenance and is not represented as Statcast xERA.
        fip = (13.0 * home_runs + 3.0 * (walks + hit_batters) - 2.0 * strikeouts) / innings + 3.10
    k_minus_bb = None
    if batters_faced and batters_faced > 0 and None not in (strikeouts, walks):
        k_minus_bb = 100.0 * (strikeouts - walks) / batters_faced

    return {
        "starter_fip": fip,
        "starter_k_minus_bb": k_minus_bb,
        "season_era": era,
        "season_whip": whip,
        "season_innings": innings,
    }


def _team_boxscore(feed: dict[str, Any], side: str) -> dict[str, Any]:
    return (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}).get(side) or {}


def _player_name(feed: dict[str, Any], person_id: int) -> str | None:
    players = ((feed.get("gameData") or {}).get("players") or {})
    player = players.get(f"ID{int(person_id)}") or players.get(str(int(person_id))) or {}
    return player.get("fullName")


def enrich_context_from_live_feed(context: PregameContext, feed: dict[str, Any]) -> PregameContext:
    game_data = feed.get("gameData") or {}
    status = game_data.get("status") or {}
    context.status_abstract = status.get("abstractGameState") or context.status_abstract
    context.status_detailed = status.get("detailedState") or context.status_detailed

    probable = game_data.get("probablePitchers") or {}
    away_pitcher = probable.get("away") or {}
    home_pitcher = probable.get("home") or {}
    if away_pitcher.get("id") is not None:
        context.away_probable_pitcher_id = int(away_pitcher["id"])
        context.away_probable_pitcher_name = away_pitcher.get("fullName")
    if home_pitcher.get("id") is not None:
        context.home_probable_pitcher_id = int(home_pitcher["id"])
        context.home_probable_pitcher_name = home_pitcher.get("fullName")
    context.probable_pitchers_confirmed = bool(
        context.away_probable_pitcher_id and context.home_probable_pitcher_id
    )

    away_order = _team_boxscore(feed, "away").get("battingOrder") or []
    home_order = _team_boxscore(feed, "home").get("battingOrder") or []
    context.away_lineup_ids = [int(pid) for pid in away_order]
    context.home_lineup_ids = [int(pid) for pid in home_order]
    context.away_lineup_names = [
        name for pid in context.away_lineup_ids if (name := _player_name(feed, pid))
    ]
    context.home_lineup_names = [
        name for pid in context.home_lineup_ids if (name := _player_name(feed, pid))
    ]
    context.lineups_confirmed = len(away_order) >= 9 and len(home_order) >= 9

    weather = game_data.get("weather") or {}
    context.temperature_f = _float_stat(weather, "temp")
    context.weather_condition = weather.get("condition")
    context.wind_description = weather.get("wind")
    context.roof_status = (game_data.get("venue") or {}).get("roofType") or context.roof_status
    return context


def apply_pitcher_stats_to_context(
    context: PregameContext,
    *,
    away_payload: dict[str, Any] | None,
    home_payload: dict[str, Any] | None,
) -> PregameContext:
    away = parse_pitcher_season_stats(away_payload or {})
    home = parse_pitcher_season_stats(home_payload or {})
    context.away_starter_fip = away["starter_fip"]
    context.home_starter_fip = home["starter_fip"]
    context.away_k_minus_bb = away["starter_k_minus_bb"]
    context.home_k_minus_bb = home["starter_k_minus_bb"]
    context.away_starter_era = away["season_era"]
    context.home_starter_era = home["season_era"]
    context.away_starter_whip = away["season_whip"]
    context.home_starter_whip = home["season_whip"]
    context.away_starter_innings = away["season_innings"]
    context.home_starter_innings = home["season_innings"]
    return context


def context_to_external_feature_record(context: PregameContext) -> dict[str, Any]:
    """Map a live context into the V2 difference-style feature contract.

    These fields are included for forward compatibility and snapshot collection. The
    current historical V2 training rows leave most advanced fields missing, so callers
    must not claim that every populated field affects today's fitted probability.
    """

    def diff(away: float | None, home: float | None, team_a_is_away: bool) -> float | None:
        if away is None or home is None:
            return None
        return away - home if team_a_is_away else home - away

    team_a_is_away = context.away_team < context.home_team
    return {
        "date": context.game_date,
        "game_pk": context.game_pk,
        "away_team": context.away_team,
        "home_team": context.home_team,
        "starter_fip_diff": diff(context.away_starter_fip, context.home_starter_fip, team_a_is_away),
        "starter_k_minus_bb_diff": diff(context.away_k_minus_bb, context.home_k_minus_bb, team_a_is_away),
        "lineup_confirmed": float(context.lineups_confirmed),
    }


def capture_live_slate(
    *,
    game_date: str,
    client: MLBStatsHTTPClient,
    snapshot_store: ImmutableSnapshotStore,
    captured_at: datetime | None = None,
) -> tuple[Path, list[Path], list[PregameContext]]:
    """Fetch and freeze the official schedule plus available per-game pregame data."""

    capture_time = captured_at or datetime.now(timezone.utc)
    if capture_time.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    schedule_payload = client.schedule(game_date)
    schedule_path = snapshot_store.write_schedule(
        raw_payload=schedule_payload,
        captured_at=capture_time,
        source="mlb_stats_api:v1/schedule",
    )
    contexts: list[PregameContext] = []
    paths: list[Path] = []
    season = int(game_date[:4])
    for record in parse_mlb_schedule(schedule_payload):
        context = PregameContext(
            game_date=record.official_date,
            away_team=record.away_team_abbreviation or record.away_team_name,
            home_team=record.home_team_abbreviation or record.home_team_name,
            game_pk=record.game_pk,
            game_datetime=record.game_datetime,
            game_number=record.game_number,
            double_header=record.double_header,
            status_abstract=record.status_abstract,
            status_detailed=record.status_detailed,
            venue_id=record.venue_id,
            venue_name=record.venue_name,
            away_team_id=record.away_team_id,
            home_team_id=record.home_team_id,
            away_probable_pitcher_id=record.away_probable_pitcher_id,
            home_probable_pitcher_id=record.home_probable_pitcher_id,
            away_probable_pitcher_name=record.away_probable_pitcher_name,
            home_probable_pitcher_name=record.home_probable_pitcher_name,
        )
        feed = client.live_feed(record.game_pk)
        enrich_context_from_live_feed(context, feed)
        away_stats = (
            client.person_pitching_stats(context.away_probable_pitcher_id, season)
            if context.away_probable_pitcher_id else {}
        )
        home_stats = (
            client.person_pitching_stats(context.home_probable_pitcher_id, season)
            if context.home_probable_pitcher_id else {}
        )
        apply_pitcher_stats_to_context(context, away_payload=away_stats, home_payload=home_stats)
        context.provenance.update({
            "schedule": "mlb_stats_api:v1/schedule",
            "live_feed": "mlb_stats_api:v1.1/game/feed/live",
            "pitcher_stats": "mlb_stats_api:v1/people/stats:season",
        })
        game_start = datetime.fromisoformat(record.game_datetime.replace("Z", "+00:00"))
        if capture_time <= game_start:
            path = snapshot_store.write_pregame(
                game_pk=record.game_pk,
                game_datetime=record.game_datetime,
                context_payload=context.to_record(),
                captured_at=capture_time,
                source="mlb_stats_api_live_capture",
            )
            paths.append(path)
        contexts.append(context)
    return schedule_path, paths, contexts


def _logit(probability: float) -> float:
    p = float(np.clip(probability, 1e-8, 1 - 1e-8))
    return math.log(p / (1 - p))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(np.clip(value, -30, 30))))


def _confidence_score(probability: float, overlap: int, model_count: int) -> float:
    probability_strength = 2.0 * abs(probability - 0.5)
    overlap_rate = overlap / model_count if model_count else 0.0
    return 0.70 * probability_strength + 0.30 * overlap_rate


def evaluate_live_slate(
    *,
    historical_features: pd.DataFrame,
    future_features: pd.DataFrame,
    moneylines: list[ManualMoneyline],
    config: LiveEvaluationConfig | None = None,
) -> pd.DataFrame:
    """Evaluate every supplied game and rank picks by model confidence.

    The engine fits the seven-model ensemble and Poisson score model, runs the requested
    Monte Carlo simulations, and reports probabilities, score expectations, model
    agreement, fair odds, and market edges. It does not size wagers or manage a bankroll.
    """

    config = config or LiveEvaluationConfig()
    if future_features.empty:
        raise ValueError("future_features cannot be empty")
    if len(moneylines) != len(future_features):
        raise ValueError("moneylines and future_features must contain the same number of games")

    odds_by_pk = {line.game_pk: line for line in moneylines if line.game_pk is not None}
    odds_by_match = {
        (line.game_date, line.away_team, line.home_team): line for line in moneylines
    }

    model = V2Ensemble().fit(historical_features)
    score_model = PoissonScoreModel().fit(historical_features)
    model_probability_a, components = model.predict_proba(future_features)
    expected_runs_a, expected_runs_b = score_model.expected_runs(future_features)
    rng = np.random.default_rng(RANDOM_SEED)
    rows: list[dict[str, Any]] = []

    for idx, (_, feature_row) in enumerate(future_features.iterrows()):
        simulation = simulate_poisson_score_distribution(
            expected_runs_a[idx], expected_runs_b[idx], config.simulations, rng
        )
        score_p_a = simulation["team_a_win_probability"]
        blended_a = (
            (1.0 - config.score_simulation_weight) * float(model_probability_a[idx])
            + config.score_simulation_weight * score_p_a
        )
        # Keep the same explicit Monte Carlo finalization used by V2 replay_dates.
        finalized_a = float(rng.binomial(1, blended_a, config.simulations).mean())
        if config.home_field_logit_adjustment:
            direction = 1.0 if float(feature_row.get("team_a_is_home", 0.0)) >= 0.5 else -1.0
            finalized_a = _sigmoid(_logit(finalized_a) + direction * config.home_field_logit_adjustment)

        away = str(feature_row["away_team"])
        home = str(feature_row["home_team"])
        team_a = str(feature_row["team_a"])
        team_b = str(feature_row["team_b"])
        team_a_is_away = team_a == away
        away_probability = finalized_a if team_a_is_away else 1.0 - finalized_a
        home_probability = 1.0 - away_probability

        component_a = {name: float(values[idx]) for name, values in components.items()}
        component_away = {
            name: (prob if team_a_is_away else 1.0 - prob) for name, prob in component_a.items()
        }
        pick = away if away_probability >= home_probability else home
        pick_probability = max(away_probability, home_probability)
        pick_is_away = pick == away
        votes_pick = sum(
            (prob >= 0.5) if pick_is_away else (prob < 0.5)
            for prob in component_away.values()
        )
        model_count = len(component_away)

        game_pk = feature_row.get("game_pk")
        line = None
        if game_pk is not None and pd.notna(game_pk):
            line = odds_by_pk.get(int(game_pk))
        if line is None:
            line = odds_by_match.get((str(feature_row["date"].date()), away, home))
        if line is None:
            raise KeyError(f"No moneyline supplied for {away}@{home}")

        away_market, home_market = no_vig_probabilities(line.away_odds, line.home_odds)
        pick_odds = line.away_odds if pick_is_away else line.home_odds
        pick_no_vig = away_market if pick_is_away else home_market
        pick_break_even = american_implied_probability(pick_odds)
        # Score means are mapped back from canonical team_a/team_b to away/home.
        a_mean = simulation["team_a_mean_runs"]
        b_mean = simulation["team_b_mean_runs"]
        away_mean = a_mean if team_a_is_away else b_mean
        home_mean = b_mean if team_a_is_away else a_mean

        def oriented_last_value(name: str) -> tuple[float, float]:
            diff_value = float(feature_row.get(f"{name}_diff", 0.0))
            sum_value = float(feature_row.get(f"{name}_sum", 0.0))
            a_value = 0.5 * (sum_value + diff_value)
            b_value = 0.5 * (sum_value - diff_value)
            return (a_value, b_value) if team_a_is_away else (b_value, a_value)

        away_last_win, home_last_win = oriented_last_value("last_win")
        away_last_rf, home_last_rf = oriented_last_value("last_rf")
        away_last_ra, home_last_ra = oriented_last_value("last_ra")
        away_last_rd, home_last_rd = oriented_last_value("last_rd")
        away_last_blowout_loss, home_last_blowout_loss = oriented_last_value("last_blowout_loss")
        away_last_was_shutout, home_last_was_shutout = oriented_last_value("last_was_shutout")

        row = {
            "game_date": str(feature_row["date"].date()),
            "game_pk": int(game_pk) if game_pk is not None and pd.notna(game_pk) else None,
            "away_team": away,
            "home_team": home,
            "away_odds": line.away_odds,
            "home_odds": line.home_odds,
            "pick": pick,
            "pick_odds": pick_odds,
            "pick_probability": pick_probability,
            "away_probability": away_probability,
            "home_probability": home_probability,
            "model_overlap": votes_pick,
            "model_count": model_count,
            "confidence_score": _confidence_score(pick_probability, votes_pick, model_count),
            "simulated_away_runs": away_mean,
            "simulated_home_runs": home_mean,
            "score_sim_away_probability": score_p_a if team_a_is_away else 1.0 - score_p_a,
            "no_vig_pick_probability": pick_no_vig,
            "break_even_probability": pick_break_even,
            "edge_vs_no_vig": pick_probability - pick_no_vig,
            "edge_vs_break_even": pick_probability - pick_break_even,
            "fair_odds": probability_to_american(pick_probability),
            "lineups_confirmed": bool(feature_row.get("lineups_confirmed", False)),
            "away_last_win": away_last_win,
            "away_last_runs_for": away_last_rf,
            "away_last_runs_against": away_last_ra,
            "away_last_run_diff": away_last_rd,
            "away_last_blowout_loss": away_last_blowout_loss,
            "away_last_was_shutout": away_last_was_shutout,
            "home_last_win": home_last_win,
            "home_last_runs_for": home_last_rf,
            "home_last_runs_against": home_last_ra,
            "home_last_run_diff": home_last_rd,
            "home_last_blowout_loss": home_last_blowout_loss,
            "home_last_was_shutout": home_last_was_shutout,
            "simulations": config.simulations,
        }
        row.update({f"p_{name}_{away}": prob for name, prob in component_away.items()})
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame = frame.sort_values(
        ["confidence_score", "pick_probability", "model_overlap"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    frame["confidence_rank"] = np.arange(1, len(frame) + 1)
    frame["is_top_pick"] = frame["confidence_rank"] <= config.top_n
    return frame



def evaluate_top_pick_parlays(
    evaluations: pd.DataFrame,
    *,
    max_legs: int = 2,
    simulations: int = 100_000,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Evaluate simple top-pick parlays under an explicit independence assumption."""

    if max_legs != 2:
        raise NotImplementedError("only two-leg parlays are currently supported")
    top = evaluations[evaluations["is_top_pick"]].copy()
    rng = np.random.default_rng(seed)
    output: list[dict[str, Any]] = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            left = top.iloc[i]
            right = top.iloc[j]
            left_draw = rng.binomial(1, float(left.pick_probability), simulations)
            right_draw = rng.binomial(1, float(right.pick_probability), simulations)
            joint = float(np.mean((left_draw == 1) & (right_draw == 1)))
            odds = combine_american_odds([int(left.pick_odds), int(right.pick_odds)])
            output.append({
                "legs": f"{left.pick} {int(left.pick_odds):+d} + {right.pick} {int(right.pick_odds):+d}",
                "combined_odds": odds,
                "joint_probability": joint,
                "break_even_probability": american_implied_probability(odds),
                "edge_vs_break_even": joint - american_implied_probability(odds),
                "assumption": "independent_game_outcomes",
                "simulations": simulations,
            })
    if not output:
        return pd.DataFrame()
    return pd.DataFrame(output).sort_values(
        ["edge_vs_break_even", "joint_probability"], ascending=[False, False]
    ).reset_index(drop=True)


def load_manual_moneylines(path: str | Path) -> list[ManualMoneyline]:
    """Backward-compatible alias for the CSV/JSON user-input loader."""

    return load_moneylines(path)


def contexts_to_matchups(contexts: list[PregameContext]) -> pd.DataFrame:
    rows = []
    for context in contexts:
        rows.append({
            "date": context.game_date,
            "game_pk": context.game_pk,
            "game_datetime": context.game_datetime,
            "away_team": context.away_team,
            "home_team": context.home_team,
            "away_starter": context.away_probable_pitcher_name or "Unknown",
            "home_starter": context.home_probable_pitcher_name or "Unknown",
            "venue_name": context.venue_name,
            "lineups_confirmed": context.lineups_confirmed,
        })
    return pd.DataFrame(rows)


def write_evaluation_artifacts(
    evaluations: pd.DataFrame,
    *,
    output_dir: str | Path,
    stem: str,
    parlays: pd.DataFrame | None = None,
) -> tuple[Path, Path | None, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / f"{stem}.csv"
    json_path = directory / f"{stem}.json"
    evaluations.to_csv(csv_path, index=False)
    json_path.write_text(
        json.dumps(evaluations.to_dict("records"), indent=2, default=str),
        encoding="utf-8",
    )
    parlay_path = None
    if parlays is not None and not parlays.empty:
        parlay_path = directory / f"{stem}_parlays.csv"
        parlays.to_csv(parlay_path, index=False)
    return csv_path, parlay_path, json_path
