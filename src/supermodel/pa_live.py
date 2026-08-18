from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import numpy as np
import pandas as pd

from .market import (
    american_implied_probability,
    no_vig_probabilities,
    probability_to_american,
)
from .mlb_v2 import RANDOM_SEED, V2Ensemble
from .odds_input import ManualMoneyline
from .pa_simulator import (
    PAInputCoverageError,
    PAGameInputs,
    PA_SIMULATOR_VERSION,
    combine_pa_event_profiles,
    hitter_profile_from_mlb_payload,
    load_pa_priors,
    pitcher_profile_from_mlb_payload,
    simulate_pa_games,
)
from .providers import PregameContext
from .selection_policy import SelectionPolicy, apply_selection_policy
from .starter_features import parse_pitcher_season_stats


PA_SHADOW_POLICY_VERSION = "pa-shadow-no-score-veto-v1"
PA_DEFAULT_MONEYLINE_WEIGHT = 0.20
PA_MINIMUM_LINEUP_STATS_COVERAGE = 8.0 / 9.0


@dataclass(frozen=True)
class PAInputAudit:
    game_pk: int
    status: str
    reasons: tuple[str, ...]
    away_lineup_coverage: float
    home_lineup_coverage: float
    bullpen_profile_source: str
    starter_workload_source: str

    def to_record(self) -> dict[str, Any]:
        return {
            "game_pk": self.game_pk,
            "status": self.status,
            "reasons": list(self.reasons),
            "away_lineup_coverage": self.away_lineup_coverage,
            "home_lineup_coverage": self.home_lineup_coverage,
            "bullpen_profile_source": self.bullpen_profile_source,
            "starter_workload_source": self.starter_workload_source,
        }


def _read_snapshot_payload(path: str | Path | None) -> Mapping[str, Any]:
    if not path:
        return {}
    target = Path(path)
    if not target.exists():
        return {}
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    payload = envelope.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _starter_raw_payload(context: PregameContext, side: str) -> Mapping[str, Any]:
    snapshot = _read_snapshot_payload(getattr(context, f"{side}_starter_stats_snapshot_path", None))
    raw = snapshot.get("raw_payload") if snapshot else None
    return raw if isinstance(raw, Mapping) else {}


def _starter_expected_batters(raw_payload: Mapping[str, Any], context: PregameContext, side: str) -> tuple[float, str]:
    parsed = parse_pitcher_season_stats(raw_payload)
    bf = parsed.get("batters_faced")
    starts = parsed.get("games_started")
    if bf is not None and starts is not None and float(starts) > 0:
        return float(np.clip(float(bf) / float(starts), 12.0, 30.0)), "season_batters_faced_per_start"
    innings = getattr(context, f"{side}_starter_innings", None)
    context_starts = getattr(context, f"{side}_starter_games_started", None)
    if innings is not None and context_starts is not None and float(context_starts) > 0:
        expected = (float(innings) / float(context_starts)) * 4.30
        return float(np.clip(expected, 12.0, 30.0)), "season_innings_per_start_proxy"
    return 21.0, "league_workload_prior"


def _advanced_raw_sources(context: PregameContext) -> Mapping[str, Any]:
    snapshot = _read_snapshot_payload(context.advanced_snapshot_path)
    raw_sources = snapshot.get("raw_sources") if snapshot else None
    return raw_sources if isinstance(raw_sources, Mapping) else {}


def build_pa_game_inputs_from_context(
    context: PregameContext,
    *,
    minimum_lineup_coverage: float = PA_MINIMUM_LINEUP_STATS_COVERAGE,
) -> tuple[PAGameInputs, PAInputAudit]:
    """Build shadow-only PA inputs from immutable point-in-time MLB snapshots.

    The adapter fails closed when starter identity, lineups, or the raw advanced snapshot
    are unavailable. Bullpen event rates prefer active-roster reliever-only season profiles;
    a team all-staff profile is retained only as an audited partial-parity fallback.
    """

    if context.game_pk is None:
        raise PAInputCoverageError("official game_pk is required")
    if not context.probable_pitchers_confirmed:
        raise PAInputCoverageError("both probable pitchers must be confirmed")
    if not context.lineups_confirmed or len(context.away_lineup_ids) < 9 or len(context.home_lineup_ids) < 9:
        raise PAInputCoverageError("both nine-player batting orders must be confirmed")

    raw_sources = _advanced_raw_sources(context)
    if not raw_sources:
        raise PAInputCoverageError("immutable advanced snapshot with raw lineup/team inputs is required")

    priors = load_pa_priors()
    prior = priors.event_probabilities
    lineups: dict[str, tuple[Any, ...]] = {}
    coverage: dict[str, float] = {}
    reasons: list[str] = []
    for side in ("away", "home"):
        lineup_source = raw_sources.get(f"{side}_lineup_stats") or {}
        payloads = lineup_source.get("payloads") if isinstance(lineup_source, Mapping) else None
        if not isinstance(payloads, list):
            raise PAInputCoverageError(f"{side} individual lineup hitting payloads are unavailable")
        payloads = payloads[:9]
        if len(payloads) != 9:
            raise PAInputCoverageError(f"{side} lineup payload does not contain nine hitters")
        valid = sum(bool(payload and isinstance(payload, Mapping)) for payload in payloads)
        side_coverage = valid / 9.0
        coverage[side] = side_coverage
        if side_coverage < minimum_lineup_coverage:
            raise PAInputCoverageError(
                f"{side} lineup stats coverage {side_coverage:.3f} is below {minimum_lineup_coverage:.3f}"
            )
        if side_coverage < 1.0:
            reasons.append(f"{side.upper()}_LINEUP_PARTIAL_PRIOR_FILL")
        lineups[side] = tuple(
            hitter_profile_from_mlb_payload(
                payload if isinstance(payload, Mapping) else {},
                prior=prior,
                source=(
                    "mlb_stats_api:season:hitting"
                    if payload and isinstance(payload, Mapping)
                    else "league_prior_missing_hitter_payload"
                ),
            )
            for payload in payloads
        )

    away_starter_raw = _starter_raw_payload(context, "away")
    home_starter_raw = _starter_raw_payload(context, "home")
    if not away_starter_raw or not home_starter_raw:
        raise PAInputCoverageError("immutable raw starter season payloads are required")
    away_starter = pitcher_profile_from_mlb_payload(
        away_starter_raw, prior=prior, source="mlb_stats_api:starter_season_pitching"
    )
    home_starter = pitcher_profile_from_mlb_payload(
        home_starter_raw, prior=prior, source="mlb_stats_api:starter_season_pitching"
    )

    bullpen_profiles: dict[str, Any] = {}
    bullpen_sources: dict[str, str] = {}
    for side in ("away", "home"):
        reliever_source = raw_sources.get(f"{side}_bullpen_pitcher_stats") or {}
        reliever_payloads = (
            reliever_source.get("payloads")
            if isinstance(reliever_source, Mapping)
            else None
        )
        reliever_profiles = [
            pitcher_profile_from_mlb_payload(
                payload,
                prior=prior,
                source="mlb_stats_api:active_roster_reliever_season_pitching",
            )
            for payload in (reliever_payloads or [])
            if isinstance(payload, Mapping)
        ]
        reliever_profiles = [profile for profile in reliever_profiles if profile.opportunities > 0]
        if reliever_profiles:
            bullpen_profiles[side] = combine_pa_event_profiles(
                reliever_profiles,
                source="mlb_stats_api:active_roster_reliever_season_pitching",
            )
            bullpen_sources[side] = "active_roster_reliever_season_pitching"
        else:
            team_pitching = raw_sources.get(f"{side}_team_pitching")
            if not isinstance(team_pitching, Mapping):
                raise PAInputCoverageError(
                    f"{side} bullpen event profile and team pitching fallback are unavailable"
                )
            bullpen_profiles[side] = pitcher_profile_from_mlb_payload(
                team_pitching,
                prior=prior,
                source="mlb_stats_api:team_season_pitching_all_staff_proxy",
            )
            bullpen_sources[side] = "team_season_pitching_all_staff_proxy"
            reasons.append(f"{side.upper()}_BULLPEN_ALL_STAFF_PROXY")
    away_bullpen = bullpen_profiles["away"]
    home_bullpen = bullpen_profiles["home"]

    # Recent bullpen workload/closer-availability fields are captured by the live context
    # pipeline, but the canonical historical PA test did not validate an event-rate or
    # reliever-selection adjustment for fatigue. Keep those fields diagnostic-only rather
    # than inventing an unvalidated live override, and make the parity gap explicit.
    reasons.append("BULLPEN_AVAILABILITY_DIAGNOSTIC_ONLY")

    away_workload, away_workload_source = _starter_expected_batters(
        away_starter_raw, context, "away"
    )
    home_workload, home_workload_source = _starter_expected_batters(
        home_starter_raw, context, "home"
    )
    workload_source = (
        away_workload_source
        if away_workload_source == home_workload_source
        else f"away={away_workload_source};home={home_workload_source}"
    )
    if "prior" in workload_source:
        reasons.append("STARTER_WORKLOAD_PRIOR_FALLBACK")

    bullpen_profile_source = (
        bullpen_sources["away"]
        if bullpen_sources["away"] == bullpen_sources["home"]
        else f"away={bullpen_sources['away']};home={bullpen_sources['home']}"
    )
    audit = PAInputAudit(
        game_pk=int(context.game_pk),
        status="PARTIAL_PARITY" if reasons else "FULL_PARITY",
        reasons=tuple(reasons),
        away_lineup_coverage=coverage["away"],
        home_lineup_coverage=coverage["home"],
        bullpen_profile_source=bullpen_profile_source,
        starter_workload_source=workload_source,
    )
    inputs = PAGameInputs(
        away_team=context.away_team,
        home_team=context.home_team,
        away_lineup=lineups["away"],
        home_lineup=lineups["home"],
        away_starter=away_starter,
        home_starter=home_starter,
        away_bullpen=away_bullpen,
        home_bullpen=home_bullpen,
        away_starter_expected_batters=away_workload,
        home_starter_expected_batters=home_workload,
        away_lineup_coverage=coverage["away"],
        home_lineup_coverage=coverage["home"],
        bullpen_profile_source=audit.bullpen_profile_source,
        source_metadata={
            "game_pk": int(context.game_pk),
            "advanced_snapshot_sha256": context.advanced_snapshot_sha256,
            "away_starter_snapshot_sha256": context.away_starter_stats_snapshot_sha256,
            "home_starter_snapshot_sha256": context.home_starter_stats_snapshot_sha256,
            "audit": audit.to_record(),
        },
    )
    return inputs, audit


def _confidence_score(probability: float, overlap: int, model_count: int) -> float:
    probability_strength = 2.0 * abs(float(probability) - 0.5)
    overlap_rate = float(overlap) / float(model_count) if model_count else 0.0
    return 0.70 * probability_strength + 0.30 * overlap_rate


def evaluate_pa_shadow_slate(
    *,
    historical_features: pd.DataFrame,
    future_features: pd.DataFrame,
    moneylines: list[ManualMoneyline],
    contexts_by_game_pk: Mapping[int, PregameContext],
    simulations: int = 100_000,
    moneyline_weight: float = PA_DEFAULT_MONEYLINE_WEIGHT,
    top_n: int = 5,
    seed: int = RANDOM_SEED,
    simulation_draws: MutableMapping[int, tuple[np.ndarray, np.ndarray]] | None = None,
) -> pd.DataFrame:
    """Run the PA implementation candidate as a third, non-authoritative shadow track."""

    if not 0.0 <= moneyline_weight <= 1.0:
        raise ValueError("moneyline_weight must be between zero and one")
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if future_features.empty:
        raise ValueError("future_features cannot be empty")

    odds_by_pk = {int(line.game_pk): line for line in moneylines if line.game_pk is not None}
    model = V2Ensemble().fit(historical_features)
    ensemble_probability_a, components = model.predict_proba(future_features)
    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for index, (_, feature_row) in enumerate(future_features.iterrows()):
        game_pk_value = feature_row.get("game_pk")
        if game_pk_value is None or pd.isna(game_pk_value):
            blocked.append({
                "game_pk": None,
                "away_team": str(feature_row.get("away_team")),
                "home_team": str(feature_row.get("home_team")),
                "pa_shadow_status": "BLOCKED",
                "pa_shadow_reasons": "MISSING_GAME_PK",
            })
            continue
        game_pk = int(game_pk_value)
        context = contexts_by_game_pk.get(game_pk)
        if context is None:
            blocked.append({
                "game_pk": game_pk,
                "away_team": str(feature_row.get("away_team")),
                "home_team": str(feature_row.get("home_team")),
                "pa_shadow_status": "BLOCKED",
                "pa_shadow_reasons": "MISSING_PREGAME_CONTEXT",
            })
            continue
        try:
            inputs, audit = build_pa_game_inputs_from_context(context)
        except PAInputCoverageError as exc:
            blocked.append({
                "game_pk": game_pk,
                "away_team": context.away_team,
                "home_team": context.home_team,
                "pa_shadow_status": "BLOCKED",
                "pa_shadow_reasons": str(exc),
            })
            continue

        result = simulate_pa_games(
            inputs,
            simulations,
            seed=int(seed) + game_pk,
            return_draws=simulation_draws is not None,
        )
        if simulation_draws is not None:
            assert result.away_runs is not None and result.home_runs is not None
            simulation_draws[game_pk] = (result.away_runs.copy(), result.home_runs.copy())

        team_a = str(feature_row["team_a"])
        away = context.away_team
        home = context.home_team
        team_a_is_away = team_a == away
        ensemble_a = float(ensemble_probability_a[index])
        ensemble_away = ensemble_a if team_a_is_away else 1.0 - ensemble_a
        pa_away = result.away_win_probability
        blended_away = (1.0 - moneyline_weight) * ensemble_away + moneyline_weight * pa_away
        blended_home = 1.0 - blended_away
        pick = away if blended_away >= 0.5 else home
        pick_is_away = pick == away
        pick_probability = blended_away if pick_is_away else blended_home

        component_a = {name: float(values[index]) for name, values in components.items()}
        component_away = {
            name: (value if team_a_is_away else 1.0 - value)
            for name, value in component_a.items()
        }
        votes_pick = sum(
            (value >= 0.5) if pick_is_away else (value < 0.5)
            for value in component_away.values()
        )
        model_count = len(component_away)

        line = odds_by_pk.get(game_pk)
        if line is None:
            raise KeyError(f"No moneyline supplied for game_pk={game_pk}")
        away_market, home_market = no_vig_probabilities(line.away_odds, line.home_odds)
        pick_odds = line.away_odds if pick_is_away else line.home_odds
        pick_no_vig = away_market if pick_is_away else home_market
        pick_break_even = american_implied_probability(pick_odds)

        score_pick = away if result.mean_away_runs >= result.mean_home_runs else home
        row: dict[str, Any] = {
            "game_date": context.game_date,
            "game_pk": game_pk,
            "away_team": away,
            "home_team": home,
            "away_odds": line.away_odds,
            "home_odds": line.home_odds,
            "pick": pick,
            "pick_odds": pick_odds,
            "pick_probability": pick_probability,
            "away_probability": blended_away,
            "home_probability": blended_home,
            "ensemble_away_probability": ensemble_away,
            "pa_away_probability": pa_away,
            "pa_home_probability": result.home_win_probability,
            "pa_moneyline_weight": float(moneyline_weight),
            "model_overlap": votes_pick,
            "model_count": model_count,
            "confidence_score": _confidence_score(pick_probability, votes_pick, model_count),
            "simulated_away_runs": result.mean_away_runs,
            "simulated_home_runs": result.mean_home_runs,
            "pa_projected_score_pick": score_pick,
            "pa_score_disagreement": score_pick != pick,
            "pa_extra_innings_probability": result.extra_innings_probability,
            "pa_away_shutout_probability": result.away_shutout_probability,
            "pa_home_shutout_probability": result.home_shutout_probability,
            "pa_game_15_plus_probability": result.game_15_plus_probability,
            "pa_five_plus_margin_probability": result.five_plus_run_margin_probability,
            "pa_one_run_game_probability": result.one_run_game_probability,
            "no_vig_pick_probability": pick_no_vig,
            "break_even_probability": pick_break_even,
            "edge_vs_no_vig": pick_probability - pick_no_vig,
            "edge_vs_break_even": pick_probability - pick_break_even,
            "fair_odds": probability_to_american(pick_probability),
            "lineups_confirmed": context.lineups_confirmed,
            "simulations": simulations,
            "pa_shadow_status": "READY",
            "pa_live_parity_status": audit.status,
            "pa_live_parity_reasons": ";".join(audit.reasons),
            "pa_away_lineup_coverage": audit.away_lineup_coverage,
            "pa_home_lineup_coverage": audit.home_lineup_coverage,
            "pa_bullpen_profile_source": audit.bullpen_profile_source,
            "pa_starter_workload_source": audit.starter_workload_source,
            "pa_simulator_version": PA_SIMULATOR_VERSION,
            "production_authority": False,
        }
        row.update({f"p_{name}_{away}": value for name, value in component_away.items()})
        rows.append(row)

    if rows:
        ready = apply_selection_policy(
            pd.DataFrame(rows),
            top_n=top_n,
            policy=SelectionPolicy(
                minimum_pick_probability=0.53,
                minimum_model_overlap=4,
                score_conflict_margin_runs=0.20,
                enable_score_conflict_veto=False,
                version=PA_SHADOW_POLICY_VERSION,
            ),
        )
    else:
        ready = pd.DataFrame()
    if blocked:
        blocked_frame = pd.DataFrame(blocked)
        blocked_frame["selection_status"] = "PASS"
        blocked_frame["eligible_for_top_pick"] = False
        blocked_frame["is_top_pick"] = False
        blocked_frame["production_authority"] = False
        if ready.empty:
            return blocked_frame
        return pd.concat([ready, blocked_frame], ignore_index=True, sort=False)
    return ready
