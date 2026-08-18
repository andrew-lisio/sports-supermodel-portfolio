from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
import math
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .execution import available_cpu_count
from .feature_attribution import leave_group_at_reference_sensitivity
from .feature_registry import group_feature_names, validate_feature_groups
from .model_contract import V24_CANDIDATE_FEATURE_CONTRACT
from .model_registry import MODEL_ORDER, validate_runtime_models

warnings.filterwarnings("ignore")

try:
    from xgboost import XGBClassifier
except Exception:  # pragma: no cover
    XGBClassifier = None
try:
    from lightgbm import LGBMClassifier
except Exception:  # pragma: no cover
    LGBMClassifier = None
try:
    from catboost import CatBoostClassifier
except Exception:  # pragma: no cover
    CatBoostClassifier = None

RANDOM_SEED = 20260720
RECENT_FORM_WINDOWS = (3, 5, 10, 20)
DEFAULT_EWM_ALPHA = V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha


@dataclass
class TeamState:
    games: int = 0
    wins: int = 0
    runs_for: float = 0.0
    runs_against: float = 0.0
    last_date: pd.Timestamp | None = None
    recent_dates: deque = field(default_factory=lambda: deque(maxlen=10))
    recent: deque = field(default_factory=lambda: deque(maxlen=20))
    opponent_adjusted_recent: deque = field(default_factory=lambda: deque(maxlen=20))
    ewm_rf: float = 4.35
    ewm_ra: float = 4.35
    ewm_win: float = 0.5
    # Explicit prior-game context. Rolling windows already contain the previous game,
    # but these fields ensure the model can learn a distinct one-game response instead
    # of diluting it inside five-, ten-, and twenty-game averages.
    last_game_known: float = 0.0
    last_win: float = 0.5
    last_rf: float = 4.35
    last_ra: float = 4.35
    last_rd: float = 0.0
    last_total_runs: float = 8.70
    last_abs_margin: float = 0.0
    last_was_home: float = 0.5
    last_opponent_win_pct: float = 0.5
    last_opponent_pyth: float = 0.5
    last_scored_shutout: float = 0.0
    last_was_shutout: float = 0.0
    last_blowout_win: float = 0.0
    last_blowout_loss: float = 0.0


@dataclass
class StarterState:
    starts: int = 0
    team_wins: int = 0
    team_runs_allowed: float = 0.0
    recent_ra: deque = field(default_factory=lambda: deque(maxlen=5))
    recent_win: deque = field(default_factory=lambda: deque(maxlen=5))


# These fields are supported by the V2 feature contract. Historical game logs used in
# this replay do not contain all of them, so absent values are neutral and accompanied
# by missingness flags. A live provider can populate them without changing model code.
LIVE_FEATURES = [
    "lineup_wrc_plus", "lineup_xwoba", "platoon_edge", "injury_war",
    "bullpen_xfip", "bullpen_siera", "bullpen_fatigue", "closer_available",
    "umpire_run_factor", "umpire_k_factor", "park_run_factor", "park_hr_factor",
    "weather_run_factor", "air_density", "wind_out_component", "rain_risk",
    "travel_fatigue", "time_zones_crossed", "defense_frv", "defense_oaa",
    "catcher_framing", "baserunning_runs", "market_implied_probability",
    "market_move", "reverse_line_move", "starter_xera", "starter_fip",
    "starter_xfip", "starter_siera", "starter_stuff_plus", "starter_location_plus",
    "starter_pitching_plus", "starter_csw", "starter_k_minus_bb",
    "starter_hard_hit_allowed", "starter_barrel_allowed", "starter_ground_ball_rate",
    "starter_velocity_trend", "starter_spin_trend", "starter_pitch_mix_change",
    "times_through_order_penalty", "lineup_confirmed",
]


def load_team_logs(data_dir: str | Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(Path(data_dir).glob("*.csv")):
        df = pd.read_csv(path)
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No team CSV files found under {data_dir}")
    return pd.concat(frames, ignore_index=True)


def reconstruct_games(team_logs: pd.DataFrame) -> pd.DataFrame:
    """Create one canonical row per date/team pair.

    The source team logs have no game identifier. Doubleheaders can collapse or collide,
    so target-date doubleheaders are explicitly excluded later using the official schedule.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[pd.Timestamp, str, str]] = set()
    logs = team_logs.copy()
    logs["team"] = logs["team"].astype(str)
    logs["opponent"] = logs["opponent"].astype(str)
    lookup = {(r.date, r.team, r.opponent): r for r in logs.itertuples(index=False)}

    for r in logs.itertuples(index=False):
        a, b = sorted((r.team, r.opponent))
        key = (r.date, a, b)
        if key in seen:
            continue
        seen.add(key)
        ar = lookup.get((r.date, a, b))
        br = lookup.get((r.date, b, a))
        if ar is None or br is None:
            continue
        a_runs = float(ar.teamruns)
        b_runs = float(br.teamruns)
        # Require reciprocal scores to be coherent. This does not fully detect all
        # doubleheader collisions, but removes obviously broken rows.
        if not np.isfinite(a_runs) or not np.isfinite(b_runs):
            continue
        rows.append({
            "date": r.date,
            "team_a": a,
            "team_b": b,
            "a_runs": a_runs,
            "b_runs": b_runs,
            "a_win": int(a_runs > b_runs),
            "a_starter": str(ar.teamstarter),
            "b_starter": str(br.teamstarter),
            "source_a_run_diff": float(ar.rundifferential),
            "source_b_run_diff": float(br.rundifferential),
        })
    out = pd.DataFrame(rows).sort_values(["date", "team_a", "team_b"]).reset_index(drop=True)
    return out


def attach_official_home_away(
    games: pd.DataFrame,
    schedule_records: Iterable[Any],
    *,
    exclude_ambiguous_doubleheaders: bool = True,
) -> pd.DataFrame:
    """Attach official home/away identity and ``gamePk`` to reconstructed games.

    The team logs do not preserve home/away or a unique game identifier. Official
    schedule records can recover those fields for normal single games. When two
    official games share the same date and teams, the source row cannot be assigned to
    a specific doubleheader game and is excluded by default.
    """

    by_pair: dict[tuple[pd.Timestamp, str, str], list[Any]] = defaultdict(list)
    for record in schedule_records:
        away = getattr(record, "away_team_abbreviation", None)
        home = getattr(record, "home_team_abbreviation", None)
        if not away or not home:
            continue
        a, b = sorted((str(away), str(home)))
        key = (pd.Timestamp(record.official_date), a, b)
        by_pair[key].append(record)

    output: list[dict[str, Any]] = []
    for game in games.to_dict("records"):
        date = pd.Timestamp(game["date"])
        team_a, team_b = str(game["team_a"]), str(game["team_b"])
        candidates = by_pair.get((date, team_a, team_b), [])
        if len(candidates) > 1 and exclude_ambiguous_doubleheaders:
            continue
        enriched = dict(game)
        if len(candidates) == 1:
            record = candidates[0]
            enriched.update({
                "game_pk": int(record.game_pk),
                "team_a_is_home": float(record.home_team_abbreviation == team_a),
                "missing_home_away": 0.0,
                "venue_name": record.venue_name,
                "double_header": record.double_header,
            })
        else:
            enriched.update({
                "game_pk": None,
                "team_a_is_home": 0.0,
                "missing_home_away": 1.0,
                "venue_name": None,
                "double_header": None,
            })
        output.append(enriched)
    if not output:
        return games.iloc[0:0].copy()
    return pd.DataFrame(output).sort_values(["date", "team_a", "team_b"]).reset_index(drop=True)


def _safe_mean(values: Iterable[float], default: float) -> float:
    vals = list(values)
    return float(np.mean(vals)) if vals else default


def _team_snapshot(
    state: TeamState,
    date: pd.Timestamp,
    *,
    include_opponent_adjusted_recent_form: bool = False,
) -> dict[str, float]:
    games = state.games
    prior_games = 10.0
    win_pct = (state.wins + prior_games * 0.5) / (games + prior_games)
    rf_pg = (state.runs_for + prior_games * 4.35) / (games + prior_games)
    ra_pg = (state.runs_against + prior_games * 4.35) / (games + prior_games)
    exponent = 1.83
    pyth = (rf_pg**exponent) / (rf_pg**exponent + ra_pg**exponent) if rf_pg + ra_pg else 0.5

    recent = list(state.recent)

    def window(n: int, idx: int, default: float) -> float:
        vals = recent[-n:]
        return _safe_mean((x[idx] for x in vals), default)

    win_windows = {n: window(n, 0, 0.5) for n in RECENT_FORM_WINDOWS}
    rf_windows = {n: window(n, 1, 4.35) for n in RECENT_FORM_WINDOWS}
    ra_windows = {n: window(n, 2, 4.35) for n in RECENT_FORM_WINDOWS}
    rd_windows = {n: window(n, 3, 0.0) for n in RECENT_FORM_WINDOWS}

    adjusted_recent = list(state.opponent_adjusted_recent)

    def adjusted_window(n: int, idx: int) -> float:
        vals = adjusted_recent[-n:]
        return _safe_mean((x[idx] for x in vals), 0.0)

    adjusted_win_windows = {
        n: adjusted_window(n, 0) for n in RECENT_FORM_WINDOWS
    }
    adjusted_rf_windows = {
        n: adjusted_window(n, 1) for n in RECENT_FORM_WINDOWS
    }
    adjusted_ra_windows = {
        n: adjusted_window(n, 2) for n in RECENT_FORM_WINDOWS
    }
    adjusted_rd_windows = {
        n: adjusted_window(n, 3) for n in RECENT_FORM_WINDOWS
    }

    if state.last_date is None:
        rest = 3.0
    else:
        rest = float(np.clip((date - state.last_date).days, 0, 7))
    games_3 = sum((date - d).days <= 3 for d in state.recent_dates)
    games_7 = sum((date - d).days <= 7 for d in state.recent_dates)

    snapshot = {
        "games": float(games), "win_pct": win_pct, "pyth": pyth,
        "rf_pg": rf_pg, "ra_pg": ra_pg, "run_diff_pg": rf_pg - ra_pg,
        **{f"win{n}": win_windows[n] for n in RECENT_FORM_WINDOWS},
        **{f"rf{n}": rf_windows[n] for n in RECENT_FORM_WINDOWS},
        **{f"ra{n}": ra_windows[n] for n in RECENT_FORM_WINDOWS},
        **{f"rd{n}": rd_windows[n] for n in RECENT_FORM_WINDOWS},
        "form_win_momentum": win_windows[3] - win_windows[10],
        "form_rf_momentum": rf_windows[3] - rf_windows[10],
        "form_ra_momentum": ra_windows[3] - ra_windows[10],
        "form_rd_momentum": rd_windows[3] - rd_windows[10],
        "ewm_rf": state.ewm_rf, "ewm_ra": state.ewm_ra, "ewm_win": state.ewm_win,
        "rest_days": rest, "games_last3": float(games_3), "games_last7": float(games_7),
        "last_game_known": state.last_game_known,
        "last_win": state.last_win,
        "last_rf": state.last_rf,
        "last_ra": state.last_ra,
        "last_rd": state.last_rd,
        "last_total_runs": state.last_total_runs,
        "last_abs_margin": state.last_abs_margin,
        "last_was_home": state.last_was_home,
        "last_opponent_win_pct": state.last_opponent_win_pct,
        "last_opponent_pyth": state.last_opponent_pyth,
        "last_scored_shutout": state.last_scored_shutout,
        "last_was_shutout": state.last_was_shutout,
        "last_blowout_win": state.last_blowout_win,
        "last_blowout_loss": state.last_blowout_loss,
    }
    if include_opponent_adjusted_recent_form:
        snapshot.update(
            {f"opp_adj_win{n}": adjusted_win_windows[n] for n in RECENT_FORM_WINDOWS}
        )
        snapshot.update(
            {f"opp_adj_rf{n}": adjusted_rf_windows[n] for n in RECENT_FORM_WINDOWS}
        )
        snapshot.update(
            {f"opp_adj_ra{n}": adjusted_ra_windows[n] for n in RECENT_FORM_WINDOWS}
        )
        snapshot.update(
            {f"opp_adj_rd{n}": adjusted_rd_windows[n] for n in RECENT_FORM_WINDOWS}
        )
        snapshot.update(
            {
                "opp_adj_form_win_momentum": (
                    adjusted_win_windows[3] - adjusted_win_windows[10]
                ),
                "opp_adj_form_rf_momentum": (
                    adjusted_rf_windows[3] - adjusted_rf_windows[10]
                ),
                "opp_adj_form_ra_momentum": (
                    adjusted_ra_windows[3] - adjusted_ra_windows[10]
                ),
                "opp_adj_form_rd_momentum": (
                    adjusted_rd_windows[3] - adjusted_rd_windows[10]
                ),
            }
        )
    return snapshot


def _starter_snapshot(state: StarterState) -> dict[str, float]:
    prior = 4.0
    return {
        "starter_starts": float(state.starts),
        "starter_team_win_pct": (state.team_wins + prior * 0.5) / (state.starts + prior),
        "starter_team_ra": (state.team_runs_allowed + prior * 4.35) / (state.starts + prior),
        "starter_recent_ra": _safe_mean(state.recent_ra, 4.35),
        "starter_recent_win": _safe_mean(state.recent_win, 0.5),
    }


def build_pregame_features(
    games: pd.DataFrame,
    external_features: pd.DataFrame | None = None,
    *,
    recent_form_alpha: float = DEFAULT_EWM_ALPHA,
    include_opponent_adjusted_recent_form: bool = False,
) -> pd.DataFrame:
    if not 0.0 < recent_form_alpha <= 1.0:
        raise ValueError("recent_form_alpha must be in (0, 1]")
    team_states: dict[str, TeamState] = defaultdict(TeamState)
    starter_states: dict[str, StarterState] = defaultdict(StarterState)
    output: list[dict[str, Any]] = []
    external_lookup_by_pk: dict[int, dict] = {}
    external_lookup_by_match: dict[tuple, dict] = {}
    if external_features is not None and not external_features.empty:
        for r in external_features.to_dict("records"):
            game_pk = r.get("game_pk")
            if game_pk is not None and pd.notna(game_pk):
                external_lookup_by_pk[int(game_pk)] = r
            key = (pd.Timestamp(r["date"]), r["team_a"], r["team_b"])
            if key in external_lookup_by_match and game_pk is None:
                raise ValueError(
                    "Ambiguous external features for a same-day matchup; include game_pk"
                )
            external_lookup_by_match[key] = r

    # Update after every full date to avoid same-day leakage.
    for date, day_games in games.groupby("date", sort=True):
        pending: list[pd.Series] = []
        for _, g in day_games.iterrows():
            a, b = g.team_a, g.team_b
            sa = _team_snapshot(
                team_states[a],
                date,
                include_opponent_adjusted_recent_form=(
                    include_opponent_adjusted_recent_form
                ),
            )
            sb = _team_snapshot(
                team_states[b],
                date,
                include_opponent_adjusted_recent_form=(
                    include_opponent_adjusted_recent_form
                ),
            )
            spa = _starter_snapshot(starter_states[g.a_starter])
            spb = _starter_snapshot(starter_states[g.b_starter])
            rec: dict[str, Any] = {
                "date": date, "team_a": a, "team_b": b,
                "a_runs": g.a_runs, "b_runs": g.b_runs, "a_win": int(g.a_win),
                "a_starter": g.a_starter, "b_starter": g.b_starter,
            }
            home_value = getattr(g, "team_a_is_home", np.nan)
            rec["team_a_is_home"] = 0.0 if pd.isna(home_value) else float(home_value)
            rec["missing_home_away"] = (
                float(getattr(g, "missing_home_away", 0.0))
                if not pd.isna(getattr(g, "missing_home_away", 0.0))
                else 1.0
            )
            for name in sa:
                rec[f"{name}_diff"] = sa[name] - sb[name]
                if name in {
                    "rf_pg", "ra_pg", "rf3", "ra3", "rf5", "ra5", "rf10", "ra10", "ewm_rf", "ewm_ra",
                    "last_win", "last_rf", "last_ra", "last_rd", "last_total_runs",
                    "last_abs_margin", "last_opponent_win_pct", "last_opponent_pyth",
                    "last_scored_shutout", "last_was_shutout",
                    "last_blowout_win", "last_blowout_loss",
                }:
                    rec[f"{name}_sum"] = sa[name] + sb[name]
            for name in spa:
                rec[f"{name}_diff"] = spa[name] - spb[name]

            game_pk = getattr(g, "game_pk", None)
            ext = (
                external_lookup_by_pk.get(int(game_pk), {})
                if game_pk is not None and not pd.isna(game_pk)
                else {}
            )
            if not ext:
                ext = external_lookup_by_match.get((date, a, b), {})
            for name in LIVE_FEATURES:
                # Difference-style values can be supplied directly as `<name>_diff`.
                # Game-level values use the plain name. NaN remains explicitly missing.
                if f"{name}_diff" in ext and pd.notna(ext[f"{name}_diff"]):
                    value = float(ext[f"{name}_diff"])
                    missing = 0.0
                elif name in ext and pd.notna(ext[name]):
                    value = float(ext[name])
                    missing = 0.0
                else:
                    value = 0.0
                    missing = 1.0
                rec[f"live_{name}"] = value
                rec[f"missing_{name}"] = missing

            output.append(rec)
            pending.append((g, sa, sb))

        for g, sa, sb in pending:
            _apply_completed_game_update(
                g=g, date=date, team_states=team_states, starter_states=starter_states,
                team_a_pregame=sa, team_b_pregame=sb,
                ewm_alpha=recent_form_alpha,
            )

    return pd.DataFrame(output)


def _opponent_adjusted_performance(
    *,
    won: float,
    runs_for: float,
    runs_against: float,
    opponent_snapshot: dict[str, float],
) -> tuple[float, float, float, float]:
    """Return point-in-time residuals versus the opponent's pregame strength.

    Positive values always represent stronger performance. Run residuals are
    clipped to keep one extreme game from dominating short rolling windows.
    """

    opponent_strength = float(
        np.clip(
            0.5
            * (
                float(opponent_snapshot["win_pct"])
                + float(opponent_snapshot["pyth"])
            ),
            0.0,
            1.0,
        )
    )
    adjusted_win = float(won) - (1.0 - opponent_strength)
    adjusted_runs_for = float(
        np.clip(runs_for - float(opponent_snapshot["ra_pg"]), -8.0, 8.0)
    )
    adjusted_runs_against = float(
        np.clip(float(opponent_snapshot["rf_pg"]) - runs_against, -8.0, 8.0)
    )
    adjusted_run_difference = float(
        np.clip(adjusted_runs_for + adjusted_runs_against, -12.0, 12.0)
    )
    return (
        adjusted_win,
        adjusted_runs_for,
        adjusted_runs_against,
        adjusted_run_difference,
    )


def _apply_completed_game_update(
    *,
    g: pd.Series,
    date: pd.Timestamp,
    team_states: dict[str, TeamState],
    starter_states: dict[str, StarterState],
    team_a_pregame: dict[str, float],
    team_b_pregame: dict[str, float],
    ewm_alpha: float = DEFAULT_EWM_ALPHA,
) -> None:
    """Apply a completed game's result while preserving explicit last-game context."""

    if not 0.0 < ewm_alpha <= 1.0:
        raise ValueError("ewm_alpha must be in (0, 1]")
    alpha = ewm_alpha
    a_home_raw = getattr(g, "team_a_is_home", np.nan)
    a_home = 0.5 if pd.isna(a_home_raw) else float(a_home_raw)
    rows = [
        (g.team_a, g.a_runs, g.b_runs, int(g.a_win), g.a_starter, a_home, team_b_pregame),
        (g.team_b, g.b_runs, g.a_runs, int(not g.a_win), g.b_starter, 1.0-a_home, team_a_pregame),
    ]
    for team, rf, ra, won, starter, was_home, opponent_snapshot in rows:
        rf, ra = float(rf), float(ra)
        rd = rf - ra
        st = team_states[str(team)]
        st.games += 1
        st.wins += int(won)
        st.runs_for += rf
        st.runs_against += ra
        st.last_date = date
        st.recent_dates.append(date)
        st.recent.append((float(won), rf, ra, rd))
        st.opponent_adjusted_recent.append(
            _opponent_adjusted_performance(
                won=float(won),
                runs_for=rf,
                runs_against=ra,
                opponent_snapshot=opponent_snapshot,
            )
        )
        st.ewm_rf = alpha * rf + (1-alpha) * st.ewm_rf
        st.ewm_ra = alpha * ra + (1-alpha) * st.ewm_ra
        st.ewm_win = alpha * float(won) + (1-alpha) * st.ewm_win

        st.last_game_known = 1.0
        st.last_win = float(won)
        st.last_rf = rf
        st.last_ra = ra
        st.last_rd = rd
        st.last_total_runs = rf + ra
        st.last_abs_margin = abs(rd)
        st.last_was_home = float(was_home)
        st.last_opponent_win_pct = float(opponent_snapshot["win_pct"])
        st.last_opponent_pyth = float(opponent_snapshot["pyth"])
        st.last_scored_shutout = float(ra == 0.0)
        st.last_was_shutout = float(rf == 0.0)
        st.last_blowout_win = float(rd >= 6.0)
        st.last_blowout_loss = float(rd <= -6.0)

        sp = starter_states[str(starter)]
        sp.starts += 1
        sp.team_wins += int(won)
        sp.team_runs_allowed += ra
        sp.recent_ra.append(ra)
        sp.recent_win.append(float(won))


def _update_states_for_game(
    g: pd.Series,
    date: pd.Timestamp,
    team_states: dict[str, TeamState],
    starter_states: dict[str, StarterState],
    *,
    recent_form_alpha: float = DEFAULT_EWM_ALPHA,
) -> None:
    """Update rolling state after one completed game without target leakage."""

    team_a_pregame = _team_snapshot(team_states[str(g.team_a)], date)
    team_b_pregame = _team_snapshot(team_states[str(g.team_b)], date)
    _apply_completed_game_update(
        g=g, date=date, team_states=team_states, starter_states=starter_states,
        team_a_pregame=team_a_pregame, team_b_pregame=team_b_pregame,
        ewm_alpha=recent_form_alpha,
    )

def _feature_record_from_states(
    *,
    date: pd.Timestamp,
    team_a: str,
    team_b: str,
    a_starter: str,
    b_starter: str,
    team_states: dict[str, TeamState],
    starter_states: dict[str, StarterState],
    external: dict[str, Any] | None = None,
    include_opponent_adjusted_recent_form: bool = False,
) -> dict[str, Any]:
    sa = _team_snapshot(
        team_states[team_a],
        date,
        include_opponent_adjusted_recent_form=include_opponent_adjusted_recent_form,
    )
    sb = _team_snapshot(
        team_states[team_b],
        date,
        include_opponent_adjusted_recent_form=include_opponent_adjusted_recent_form,
    )
    spa, spb = _starter_snapshot(starter_states[a_starter]), _starter_snapshot(starter_states[b_starter])
    rec: dict[str, Any] = {
        "date": date,
        "team_a": team_a,
        "team_b": team_b,
        "a_starter": a_starter,
        "b_starter": b_starter,
    }
    for name in sa:
        rec[f"{name}_diff"] = sa[name] - sb[name]
        if name in {
            "rf_pg", "ra_pg", "rf3", "ra3", "rf5", "ra5", "rf10", "ra10", "ewm_rf", "ewm_ra",
            "last_win", "last_rf", "last_ra", "last_rd", "last_total_runs",
            "last_abs_margin", "last_opponent_win_pct", "last_opponent_pyth",
            "last_scored_shutout", "last_was_shutout",
            "last_blowout_win", "last_blowout_loss",
        }:
            rec[f"{name}_sum"] = sa[name] + sb[name]
    for name in spa:
        rec[f"{name}_diff"] = spa[name] - spb[name]

    ext = external or {}
    for name in LIVE_FEATURES:
        if f"{name}_diff" in ext and pd.notna(ext[f"{name}_diff"]):
            value = float(ext[f"{name}_diff"])
            missing = 0.0
        elif name in ext and pd.notna(ext[name]):
            value = float(ext[name])
            missing = 0.0
        else:
            value = 0.0
            missing = 1.0
        rec[f"live_{name}"] = value
        rec[f"missing_{name}"] = missing
    return rec


def build_future_features(
    historical_games: pd.DataFrame,
    matchups: pd.DataFrame,
    external_features: pd.DataFrame | None = None,
    *,
    recent_form_alpha: float = DEFAULT_EWM_ALPHA,
    include_opponent_adjusted_recent_form: bool = False,
) -> pd.DataFrame:
    """Build leakage-safe feature rows for future MLB matchups.

    ``matchups`` must contain ``date``, ``away_team``, ``home_team``,
    ``away_starter`` and ``home_starter``. Official ``game_pk`` is strongly
    recommended and is preserved when supplied. The trained V2 contract uses a
    canonical alphabetical ``team_a``/``team_b`` orientation; away/home identity is
    retained separately for reporting and downstream home-field adjustment.

    This function intentionally refuses target dates that overlap completed training
    dates. Same-day historical logs do not contain reliable game ordering and could
    leak later results into an earlier game.
    """

    required = {"date", "away_team", "home_team", "away_starter", "home_starter"}
    missing = required.difference(matchups.columns)
    if missing:
        raise ValueError(f"matchups missing required columns: {sorted(missing)}")
    if historical_games.empty:
        raise ValueError("historical_games cannot be empty")

    history = historical_games.copy().sort_values(["date", "team_a", "team_b"])
    history["date"] = pd.to_datetime(history["date"])
    targets = matchups.copy()
    targets["date"] = pd.to_datetime(targets["date"])
    if targets["date"].min() <= history["date"].max():
        raise ValueError(
            "future matchup dates must be later than the latest completed historical date"
        )

    if not 0.0 < recent_form_alpha <= 1.0:
        raise ValueError("recent_form_alpha must be in (0, 1]")
    team_states: dict[str, TeamState] = defaultdict(TeamState)
    starter_states: dict[str, StarterState] = defaultdict(StarterState)
    for date, day_games in history.groupby("date", sort=True):
        for _, game in day_games.iterrows():
            _update_states_for_game(
                game,
                date,
                team_states,
                starter_states,
                recent_form_alpha=recent_form_alpha,
            )

    ext_by_game_pk: dict[int, dict[str, Any]] = {}
    ext_by_matchup: dict[tuple[pd.Timestamp, str, str], dict[str, Any]] = {}
    if external_features is not None and not external_features.empty:
        ext_frame = external_features.copy()
        ext_frame["date"] = pd.to_datetime(ext_frame["date"])
        for record in ext_frame.to_dict("records"):
            if record.get("game_pk") is not None and pd.notna(record.get("game_pk")):
                ext_by_game_pk[int(record["game_pk"])] = record
            ext_by_matchup[(record["date"], str(record["away_team"]), str(record["home_team"]))] = record

    output: list[dict[str, Any]] = []
    sort_cols = ["date"] + (["game_pk"] if "game_pk" in targets.columns else [])
    for record in targets.sort_values(sort_cols).to_dict("records"):
        away, home = str(record["away_team"]), str(record["home_team"])
        team_a, team_b = sorted((away, home))
        if team_a == away:
            a_starter, b_starter = str(record["away_starter"]), str(record["home_starter"])
        else:
            a_starter, b_starter = str(record["home_starter"]), str(record["away_starter"])
        game_pk = record.get("game_pk")
        ext = None
        if game_pk is not None and pd.notna(game_pk):
            ext = ext_by_game_pk.get(int(game_pk))
        if ext is None:
            ext = ext_by_matchup.get((record["date"], away, home))

        rec = _feature_record_from_states(
            date=record["date"],
            team_a=team_a,
            team_b=team_b,
            a_starter=a_starter,
            b_starter=b_starter,
            team_states=team_states,
            starter_states=starter_states,
            external=ext,
            include_opponent_adjusted_recent_form=(
                include_opponent_adjusted_recent_form
            ),
        )
        rec.update({
            "game_pk": int(game_pk) if game_pk is not None and pd.notna(game_pk) else None,
            "away_team": away,
            "home_team": home,
            "away_starter": str(record["away_starter"]),
            "home_starter": str(record["home_starter"]),
            "team_a_is_home": float(team_a == home),
            "missing_home_away": 0.0,
            "game_datetime": record.get("game_datetime"),
            "venue_name": record.get("venue_name"),
            "lineups_confirmed": bool(record.get("lineups_confirmed", False)),
        })
        output.append(rec)
    return pd.DataFrame(output)


def feature_columns(df: pd.DataFrame) -> list[str]:
    meta = {"date", "team_a", "team_b", "a_runs", "b_runs", "a_win", "a_starter", "b_starter"}
    columns = [c for c in df.columns if c not in meta and pd.api.types.is_numeric_dtype(df[c])]
    # V2.4 fails closed when a newly added numeric feature has not been assigned to
    # a baseball category.  Validation does not reorder or alter model inputs.
    validate_feature_groups(columns)
    return columns


def v1_baseline_probability(df: pd.DataFrame) -> np.ndarray:
    # Frozen V1-style formula used only as a broad validation baseline.
    z = (
        2.2 * df["pyth_diff"] + 1.5 * df["win_pct_diff"] +
        0.9 * df["win10_diff"] + 0.55 * df["starter_team_win_pct_diff"] -
        0.18 * df["starter_team_ra_diff"] + 0.18 * df["rest_days_diff"] -
        0.10 * df["games_last3_diff"]
    )
    return 1.0 / (1.0 + np.exp(-np.clip(z, -8, 8)))


class EloPythModel:
    """Deterministic seventh component based on smoothed team strength."""
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "EloPythModel":
        return self
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        z = (
            2.5 * X["pyth_diff"].to_numpy() +
            1.4 * X["win_pct_diff"].to_numpy() +
            0.75 * X["ewm_win_diff"].to_numpy() +
            0.15 * X["rest_days_diff"].to_numpy()
        )
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -8, 8)))
        return np.column_stack([1-p, p])


def make_models(
    *,
    model_workers: int | None = None,
    estimator_threads: int = 1,
    parallel_jobs: int | None = None,
) -> dict[str, Any]:
    """Construct the frozen seven-model registry in canonical order.

    ``parallel_jobs`` is retained as a compatibility alias for older callers. It now
    controls native estimator threads only; independent model-level parallelism is
    handled by :class:`V2Ensemble`.
    """

    if parallel_jobs is not None:
        estimator_threads = parallel_jobs
    if estimator_threads == -1:
        estimator_threads = max(1, model_workers or 1)
    if estimator_threads <= 0:
        raise ValueError("estimator_threads must be positive or -1")

    models: dict[str, Any] = {
        "logistic": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=0.35, max_iter=1500, random_state=RANDOM_SEED)),
        ]),
        "random_forest": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(
                n_estimators=120, max_depth=5, min_samples_leaf=14,
                max_features="sqrt", class_weight="balanced_subsample",
                random_state=RANDOM_SEED, n_jobs=estimator_threads,
            )),
        ]),
        "neural_network": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", MLPClassifier(
                hidden_layer_sizes=(32, 16), alpha=0.025, learning_rate_init=0.002,
                max_iter=220, early_stopping=True, validation_fraction=0.18,
                random_state=RANDOM_SEED,
            )),
        ]),
        "elo_pyth": EloPythModel(),
    }
    if XGBClassifier is not None:
        models["xgboost"] = XGBClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.035,
            subsample=0.8, colsample_bytree=0.75, reg_lambda=4.0,
            min_child_weight=8, eval_metric="logloss", random_state=RANDOM_SEED,
            n_jobs=estimator_threads, tree_method="hist",
        )
    if LGBMClassifier is not None:
        models["lightgbm"] = LGBMClassifier(
            n_estimators=100, num_leaves=11, max_depth=4, learning_rate=0.035,
            min_child_samples=20, reg_lambda=4.0, reg_alpha=0.5,
            verbosity=-1, random_state=RANDOM_SEED, n_jobs=estimator_threads,
        )
    if CatBoostClassifier is not None:
        models["catboost"] = CatBoostClassifier(
            iterations=100, depth=4, learning_rate=0.035, l2_leaf_reg=6,
            verbose=False, random_seed=RANDOM_SEED, allow_writing_files=False, thread_count=estimator_threads,
        )
    missing = [name for name in MODEL_ORDER if name not in models]
    if missing:
        raise RuntimeError(
            "The complete seven-model ensemble is required. Missing components: "
            + ", ".join(missing)
            + ". Install the dependencies declared in pyproject.toml."
        )
    # Rebuild in canonical order before validation so optional import order can never
    # silently change component weighting or reporting.
    models = {name: models[name] for name in MODEL_ORDER}
    validate_runtime_models(models)
    return models


class V2Ensemble:
    def __init__(
        self,
        *,
        model_workers: int | None = None,
        estimator_threads: int = 1,
        parallel_jobs: int | None = None,
    ) -> None:
        if parallel_jobs is not None:
            # Backward-compatible interpretation: one outer worker and the requested
            # native estimator budget. Existing experiment callers pass 1.
            estimator_threads = parallel_jobs
            if model_workers is None:
                model_workers = 1
        self.model_workers = max(
            1,
            min(
                int(model_workers or available_cpu_count()),
                len(MODEL_ORDER),
            ),
        )
        self.estimator_threads = estimator_threads
        self.models = make_models(
            model_workers=self.model_workers,
            estimator_threads=estimator_threads,
        )
        self.feature_names: list[str] = []
        self.feature_groups: dict[str, list[str]] = {}
        self.feature_reference_values: dict[str, float] = {}
        self.weights: dict[str, float] = {}
        self.calibrator: LogisticRegression | None = None
        self.v1_anchor_weight: float = 0.25

    def fit(self, train: pd.DataFrame) -> "V2Ensemble":
        self.feature_names = feature_columns(train)
        self.feature_groups = group_feature_names(self.feature_names)
        train = train.sort_values("date")
        split = max(100, int(len(train) * 0.8))
        split = min(split, len(train)-30)
        core, cal = train.iloc[:split], train.iloc[split:]
        self.feature_reference_values = {
            name: (
                float(value) if pd.notna(value) and np.isfinite(float(value)) else 0.0
            )
            for name, value in core[self.feature_names].median(numeric_only=True).items()
        }
        Xc, yc = core[self.feature_names], core["a_win"]
        Xcal, ycal = cal[self.feature_names], cal["a_win"]

        def fit_component(item: tuple[str, Any]) -> tuple[str, np.ndarray]:
            name, model = item
            model.fit(Xc, yc)
            return name, model.predict_proba(Xcal)[:, 1]

        items = list(self.models.items())
        if self.model_workers == 1:
            fitted = [fit_component(item) for item in items]
        else:
            with ThreadPoolExecutor(
                max_workers=self.model_workers,
                thread_name_prefix="supermodel-fit",
            ) as executor:
                fitted = list(executor.map(fit_component, items))
        cal_probs = dict(fitted)

        briers = {name: brier_score_loss(ycal, p) for name, p in cal_probs.items()}
        raw_w = {name: math.exp(-10.0 * b) for name, b in briers.items()}
        total = sum(raw_w.values())
        self.weights = {name: w/total for name, w in raw_w.items()}
        raw_cal = sum(self.weights[n] * cal_probs[n] for n in self.models)
        self.calibrator = LogisticRegression(C=0.2, max_iter=1000, random_state=RANDOM_SEED)
        self.calibrator.fit(raw_cal.reshape(-1, 1), ycal)
        ml_cal = self.calibrator.predict_proba(raw_cal.reshape(-1, 1))[:, 1]
        v1_cal = v1_baseline_probability(cal)
        # Select the V1 prior-anchor weight only on the chronological calibration slice.
        # This makes V2 a conservative stacked upgrade rather than an unbounded replacement.
        grid = [0.0, 0.25, 0.5, 0.75, 1.0]
        self.v1_anchor_weight = min(
            grid, key=lambda w: brier_score_loss(ycal, w*v1_cal + (1-w)*ml_cal)
        )

        # Keep the chronologically trained core models. The final 20% is reserved for
        # calibration, preventing same-window leakage and cutting retraining cost.
        return self

    def component_probabilities(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        X = df[self.feature_names]

        def predict_component(item: tuple[str, Any]) -> tuple[str, np.ndarray]:
            name, model = item
            return name, model.predict_proba(X)[:, 1]

        items = list(self.models.items())
        if self.model_workers == 1 or len(df) < 2:
            predicted = [predict_component(item) for item in items]
        else:
            with ThreadPoolExecutor(
                max_workers=self.model_workers,
                thread_name_prefix="supermodel-predict",
            ) as executor:
                predicted = list(executor.map(predict_component, items))
        return dict(predicted)

    def predict_proba(self, df: pd.DataFrame) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        comp = self.component_probabilities(df)
        raw = sum(self.weights[n] * comp[n] for n in self.models)
        if self.calibrator is None:
            calibrated = raw
        else:
            calibrated = self.calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]
        # Preserve a calibrated fraction of the frozen V1 prior. The weight was chosen
        # without looking at the prediction window.
        v1 = np.asarray(v1_baseline_probability(df), dtype=float)
        calibrated = np.asarray(calibrated, dtype=float)
        calibrated = self.v1_anchor_weight * v1 + (1-self.v1_anchor_weight) * calibrated
        calibrated = np.clip(calibrated, 0.08, 0.92)
        return calibrated, comp

    def group_sensitivities(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return non-additive feature-group sensitivity in canonical team-A orientation.

        Each group is replaced with medians learned from the chronological training core,
        then the fitted ensemble is evaluated again. These diagnostics explain model
        sensitivity; they do not alter the probability and are not causal attributions.
        """

        if not self.feature_reference_values:
            raise RuntimeError("V2Ensemble must be fitted before attribution")
        baseline, _ = self.predict_proba(df)
        return leave_group_at_reference_sensitivity(
            df,
            baseline_probability=baseline,
            predict_probability=lambda neutral: self.predict_proba(neutral)[0],
            feature_groups=self.feature_groups,
            reference_values=self.feature_reference_values,
        )


class PoissonScoreModel:
    """Train separate leakage-safe expected-run models for the canonical teams."""

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.feature_names: list[str] = []
        self.feature_groups: dict[str, list[str]] = {}
        self.team_a_model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", PoissonRegressor(
                alpha=alpha, solver="newton-cholesky", max_iter=100
            )),
        ])
        self.team_b_model = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", PoissonRegressor(
                alpha=alpha, solver="newton-cholesky", max_iter=100
            )),
        ])

    def fit(self, train: pd.DataFrame) -> "PoissonScoreModel":
        if train.empty:
            raise ValueError("train cannot be empty")
        # Advanced live fields are mostly constant/missing in the current historical
        # set and make the Poisson optimizer slower without adding trained signal.
        self.feature_names = [
            name for name in feature_columns(train)
            if not name.startswith("live_") and not name.startswith("missing_")
        ]
        self.feature_groups = group_feature_names(self.feature_names)
        X = train[self.feature_names]
        self.team_a_model.fit(X, train["a_runs"].clip(lower=0))
        self.team_b_model.fit(X, train["b_runs"].clip(lower=0))
        return self

    def expected_runs(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        if not self.feature_names:
            raise RuntimeError("PoissonScoreModel must be fitted before prediction")
        X = df[self.feature_names]
        a = np.clip(self.team_a_model.predict(X), 1.2, 9.0)
        b = np.clip(self.team_b_model.predict(X), 1.2, 9.0)
        return np.asarray(a, dtype=float), np.asarray(b, dtype=float)


def metric_row(y: pd.Series, p: np.ndarray) -> dict[str, float]:
    return {
        "n": int(len(y)),
        "accuracy": float(accuracy_score(y, p >= 0.5)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0,1])),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
    }


def walk_forward_trials(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    windows = [
        ("2026-04-20", "2026-05-10"),
        ("2026-05-11", "2026-05-31"),
        ("2026-06-01", "2026-06-20"),
        ("2026-06-21", "2026-07-05"),
        ("2026-07-06", "2026-07-16"),
    ]
    predictions: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for start_s, end_s in windows:
        start, end = pd.Timestamp(start_s), pd.Timestamp(end_s)
        train = features[features.date < start]
        val = features[(features.date >= start) & (features.date <= end)].copy()
        if len(train) < 150 or val.empty:
            continue
        model = V2Ensemble().fit(train)
        p2, comp = model.predict_proba(val)
        p1 = v1_baseline_probability(val)
        val["v1_probability"] = p1
        val["v2_probability"] = p2
        for n, p in comp.items():
            val[f"component_{n}"] = p
        predictions.append(val)
        r1 = metric_row(val.a_win, p1)
        r2 = metric_row(val.a_win, p2)
        fold_rows.append({"window_start": start_s, "window_end": end_s,
                          "train_n": len(train), "validation_n": len(val),
                          **{f"v1_{k}":v for k,v in r1.items()},
                          **{f"v2_{k}":v for k,v in r2.items()}})
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(fold_rows)


def walk_forward_operational_trials(
    features: pd.DataFrame,
    *,
    score_weight: float = 0.20,
    simulations: int = 10_000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate the V2.2 ensemble plus trained Poisson score simulation chronologically."""

    if not 0.0 <= score_weight <= 1.0:
        raise ValueError("score_weight must be between 0 and 1")
    windows = [
        ("2026-04-20", "2026-05-10"),
        ("2026-05-11", "2026-05-31"),
        ("2026-06-01", "2026-06-20"),
        ("2026-06-21", "2026-07-05"),
        ("2026-07-06", "2026-07-16"),
    ]
    rng = np.random.default_rng(RANDOM_SEED)
    predictions: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for start_s, end_s in windows:
        start, end = pd.Timestamp(start_s), pd.Timestamp(end_s)
        train = features[features.date < start]
        val = features[(features.date >= start) & (features.date <= end)].copy()
        if len(train) < 150 or val.empty:
            continue
        winner_model = V2Ensemble().fit(train)
        score_model = PoissonScoreModel().fit(train)
        p_winner, comp = winner_model.predict_proba(val)
        expected_a, expected_b = score_model.expected_runs(val)
        score_probs = simulate_poisson_batch_probabilities(
            expected_a, expected_b, simulations, rng
        )
        p_operational = (1.0 - score_weight) * p_winner + score_weight * score_probs
        val["v1_probability"] = v1_baseline_probability(val)
        val["v2_probability"] = p_winner
        val["score_probability"] = score_probs
        val["v2_2_probability"] = p_operational
        val["expected_a_runs"] = expected_a
        val["expected_b_runs"] = expected_b
        for name, probability in comp.items():
            val[f"component_{name}"] = probability
        predictions.append(val)
        base_metrics = metric_row(val.a_win, p_winner)
        operational_metrics = metric_row(val.a_win, p_operational)
        fold_rows.append({
            "window_start": start_s,
            "window_end": end_s,
            "train_n": len(train),
            "validation_n": len(val),
            **{f"v2_{key}": value for key, value in base_metrics.items()},
            **{f"v2_2_{key}": value for key, value in operational_metrics.items()},
        })
    if not predictions:
        return pd.DataFrame(), pd.DataFrame(fold_rows)
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(fold_rows)


def simulate_score_distribution(
    row: pd.Series,
    n: int,
    rng: np.random.Generator,
    *,
    return_draws: bool = False,
) -> dict[str, Any]:
    """Simulate one canonical matchup and return probability plus score summaries."""

    if n <= 0:
        raise ValueError("n must be positive")
    league = 4.35
    a_off = max(2.0, row.get("rf10_diff", 0.0)/2 + row.get("rf10_sum", 2*league)/2)
    b_off = max(2.0, -row.get("rf10_diff", 0.0)/2 + row.get("rf10_sum", 2*league)/2)
    a_def = max(2.0, row.get("ra10_diff", 0.0)/2 + row.get("ra10_sum", 2*league)/2)
    b_def = max(2.0, -row.get("ra10_diff", 0.0)/2 + row.get("ra10_sum", 2*league)/2)
    a_lambda = np.clip(league * (a_off/league) * (b_def/league), 2.2, 7.2)
    b_lambda = np.clip(league * (b_off/league) * (a_def/league), 2.2, 7.2)
    env = rng.gamma(shape=18.0, scale=1/18.0, size=n)
    ar = rng.poisson(a_lambda * env)
    br = rng.poisson(b_lambda * env)
    wins = (ar > br).astype(float)
    ties = ar == br
    if ties.any():
        wins[ties] = rng.binomial(1, 0.5, ties.sum())
    result: dict[str, Any] = {
        "team_a_win_probability": float(wins.mean()),
        "team_a_mean_runs": float(ar.mean()),
        "team_b_mean_runs": float(br.mean()),
        "team_a_median_runs": float(np.median(ar)),
        "team_b_median_runs": float(np.median(br)),
        "tie_rate_before_resolution": float(ties.mean()),
        "simulations": float(n),
    }
    if return_draws:
        result["team_a_runs"] = ar.astype(np.int16, copy=False)
        result["team_b_runs"] = br.astype(np.int16, copy=False)
    return result


def simulate_poisson_score_distribution(
    team_a_expected_runs: float,
    team_b_expected_runs: float,
    n: int,
    rng: np.random.Generator,
    *,
    return_draws: bool = False,
) -> dict[str, Any]:
    """Simulate a correlated score distribution from trained expected-run inputs."""

    if n <= 0:
        raise ValueError("n must be positive")
    if team_a_expected_runs <= 0 or team_b_expected_runs <= 0:
        raise ValueError("expected runs must be positive")
    env = rng.gamma(shape=18.0, scale=1 / 18.0, size=n)
    ar = rng.poisson(float(team_a_expected_runs) * env)
    br = rng.poisson(float(team_b_expected_runs) * env)
    wins = (ar > br).astype(float)
    ties = ar == br
    if ties.any():
        wins[ties] = rng.binomial(1, 0.5, ties.sum())
    result: dict[str, Any] = {
        "team_a_win_probability": float(wins.mean()),
        "team_a_mean_runs": float(ar.mean()),
        "team_b_mean_runs": float(br.mean()),
        "team_a_median_runs": float(np.median(ar)),
        "team_b_median_runs": float(np.median(br)),
        "tie_rate_before_resolution": float(ties.mean()),
        "simulations": float(n),
    }
    if return_draws:
        result["team_a_runs"] = ar.astype(np.int16, copy=False)
        result["team_b_runs"] = br.astype(np.int16, copy=False)
    return result


def simulate_poisson_batch_probabilities(
    team_a_expected_runs: np.ndarray,
    team_b_expected_runs: np.ndarray,
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Vectorized win probabilities for many games under the score model."""

    a = np.asarray(team_a_expected_runs, dtype=float)
    b = np.asarray(team_b_expected_runs, dtype=float)
    if a.shape != b.shape:
        raise ValueError("expected-run arrays must have the same shape")
    if n <= 0 or np.any(a <= 0) or np.any(b <= 0):
        raise ValueError("n and expected runs must be positive")
    env = rng.gamma(shape=18.0, scale=1 / 18.0, size=(len(a), n))
    ar = rng.poisson(a[:, None] * env)
    br = rng.poisson(b[:, None] * env)
    wins = (ar > br).astype(float)
    ties = ar == br
    tie_count = int(ties.sum())
    if tie_count:
        wins[ties] = rng.binomial(1, 0.5, tie_count)
    return wins.mean(axis=1)


def _score_sim_probability(row: pd.Series, n: int, rng: np.random.Generator) -> float:
    return simulate_score_distribution(row, n, rng)["team_a_win_probability"]


def replay_dates(features: pd.DataFrame, dates: list[str], simulations: int = 100_000,
                 excluded_pairs: set[tuple[str,str,str]] | None = None) -> pd.DataFrame:
    excluded_pairs = excluded_pairs or set()
    out: list[dict[str, Any]] = []
    rng = np.random.default_rng(RANDOM_SEED)
    for date_s in dates:
        date = pd.Timestamp(date_s)
        train = features[features.date < date]
        target = features[features.date == date].copy()
        if target.empty:
            continue
        model = V2Ensemble().fit(train)
        p, comps = model.predict_proba(target)
        for idx, (_, row) in enumerate(target.iterrows()):
            pair = (date_s, row.team_a, row.team_b)
            if pair in excluded_pairs:
                continue
            score_p = _score_sim_probability(row, simulations, rng)
            blended = float(0.80 * p[idx] + 0.20 * score_p)
            simulated = float(rng.binomial(1, blended, simulations).mean())
            votes_a = sum(float(cp[idx]) >= 0.5 for cp in comps.values())
            pick = row.team_a if simulated >= 0.5 else row.team_b
            pick_prob = simulated if simulated >= 0.5 else 1-simulated
            actual = row.team_a if row.a_win else row.team_b
            out.append({
                "date": date_s, "team_a": row.team_a, "team_b": row.team_b,
                "matchup_canonical": f"{row.team_a}-{row.team_b}",
                "v2_pick": pick, "v2_probability": pick_prob,
                "team_a_probability": simulated, "score_sim_team_a_probability": score_p,
                "model_votes_team_a": votes_a, "model_count": len(comps),
                "actual_winner": actual, "correct": int(pick == actual),
                "simulations": simulations,
                **{f"p_{name}": float(cp[idx]) for name, cp in comps.items()},
            })
    return pd.DataFrame(out)
