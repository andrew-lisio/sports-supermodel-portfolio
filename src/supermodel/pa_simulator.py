from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


PA_SIMULATOR_VERSION = "pa-generative-shadow-rc1"
PA_EVENT_ORDER: tuple[str, ...] = (
    "K",
    "BB",
    "HBP",
    "1B",
    "2B",
    "3B",
    "HR",
    "REACH",
    "OUT",
)
PA_EVENT_INDEX = {name: index for index, name in enumerate(PA_EVENT_ORDER)}

# Frozen from the canonical 2024-development evaluation.
BATTER_PRIOR_PA = 60.0
STARTER_PRIOR_PA = 90.0
BULLPEN_PRIOR_PA = 240.0
BATTER_RELATIVE_RATE_EXPONENT = 0.5
PITCHER_RELATIVE_RATE_EXPONENT = 0.5
HOME_NON_OUT_MULTIPLIER = 1.04
GLOBAL_EVENT_MULTIPLIER = 1.0


class PAInputCoverageError(ValueError):
    """Raised when a live PA shadow cannot be built without fabricating inputs."""


@dataclass(frozen=True)
class PAEventProfile:
    counts: tuple[float, ...]
    opportunities: float
    source: str

    def __post_init__(self) -> None:
        if len(self.counts) != len(PA_EVENT_ORDER):
            raise ValueError("counts must follow PA_EVENT_ORDER")
        if self.opportunities < 0:
            raise ValueError("opportunities cannot be negative")
        if any((not math.isfinite(float(value)) or float(value) < 0) for value in self.counts):
            raise ValueError("profile counts must be finite and non-negative")

    def posterior_rates(self, prior: np.ndarray, prior_strength: float) -> np.ndarray:
        prior_array = np.asarray(prior, dtype=float)
        if prior_array.shape != (len(PA_EVENT_ORDER),):
            raise ValueError("prior has the wrong shape")
        if prior_strength < 0:
            raise ValueError("prior_strength cannot be negative")
        counts = np.asarray(self.counts, dtype=float)
        denominator = float(self.opportunities) + float(prior_strength)
        if denominator <= 0:
            return prior_array.copy()
        rates = (counts + float(prior_strength) * prior_array) / denominator
        rates = np.clip(rates, 1e-12, None)
        return rates / rates.sum()


@dataclass(frozen=True)
class PAGameInputs:
    away_team: str
    home_team: str
    away_lineup: tuple[PAEventProfile, ...]
    home_lineup: tuple[PAEventProfile, ...]
    away_starter: PAEventProfile
    home_starter: PAEventProfile
    away_bullpen: PAEventProfile
    home_bullpen: PAEventProfile
    away_starter_expected_batters: float
    home_starter_expected_batters: float
    away_lineup_coverage: float = 1.0
    home_lineup_coverage: float = 1.0
    bullpen_profile_source: str = "unknown"
    source_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if len(self.away_lineup) != 9 or len(self.home_lineup) != 9:
            raise ValueError("PA simulation requires exactly nine hitters per lineup")
        if self.away_starter_expected_batters <= 0 or self.home_starter_expected_batters <= 0:
            raise ValueError("starter workload must be positive")
        for coverage in (self.away_lineup_coverage, self.home_lineup_coverage):
            if not 0.0 <= float(coverage) <= 1.0:
                raise ValueError("lineup coverage must be in [0, 1]")


@dataclass(frozen=True)
class PASimulationResult:
    away_win_probability: float
    home_win_probability: float
    mean_away_runs: float
    mean_home_runs: float
    median_away_runs: float
    median_home_runs: float
    extra_innings_probability: float
    away_shutout_probability: float
    home_shutout_probability: float
    game_15_plus_probability: float
    five_plus_run_margin_probability: float
    one_run_game_probability: float
    simulations: int
    seed: int
    away_runs: np.ndarray | None = None
    home_runs: np.ndarray | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "away_win_probability": self.away_win_probability,
            "home_win_probability": self.home_win_probability,
            "mean_away_runs": self.mean_away_runs,
            "mean_home_runs": self.mean_home_runs,
            "median_away_runs": self.median_away_runs,
            "median_home_runs": self.median_home_runs,
            "extra_innings_probability": self.extra_innings_probability,
            "away_shutout_probability": self.away_shutout_probability,
            "home_shutout_probability": self.home_shutout_probability,
            "game_15_plus_probability": self.game_15_plus_probability,
            "five_plus_run_margin_probability": self.five_plus_run_margin_probability,
            "one_run_game_probability": self.one_run_game_probability,
            "simulations": self.simulations,
            "seed": self.seed,
            "simulator_version": PA_SIMULATOR_VERSION,
        }


@dataclass(frozen=True)
class PAPriors:
    event_probabilities: np.ndarray
    transitions: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]]
    source: str


def _resource_path() -> Path:
    resource = files("supermodel").joinpath("resources/pa_priors_2024.json")
    return Path(str(resource))


def load_pa_priors(path: str | Path | None = None) -> PAPriors:
    target = Path(path) if path is not None else _resource_path()
    payload = json.loads(target.read_text(encoding="utf-8"))
    order = tuple(payload.get("event_order") or ())
    if order != PA_EVENT_ORDER:
        raise ValueError("PA prior event order does not match simulator contract")
    probabilities = np.asarray(
        [float(payload["event_probabilities"][name]) for name in PA_EVENT_ORDER],
        dtype=float,
    )
    probabilities = np.clip(probabilities, 1e-12, None)
    probabilities /= probabilities.sum()
    transitions: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}
    for key, outcomes in payload["transitions"].items():
        outs_text, base_text, event_name = key.split(":", 2)
        event_index = PA_EVENT_INDEX[event_name]
        values = np.asarray(
            [
                [int(item["outs_added"]), int(item["next_base_mask"]), int(item["runs"])]
                for item in outcomes
            ],
            dtype=np.int16,
        )
        probabilities_outcome = np.asarray(
            [float(item["probability"]) for item in outcomes], dtype=float
        )
        probabilities_outcome = np.clip(probabilities_outcome, 0.0, None)
        probabilities_outcome /= probabilities_outcome.sum()
        transitions[(int(outs_text), int(base_text), event_index)] = (
            values,
            np.cumsum(probabilities_outcome),
        )
    expected_keys = 3 * 8 * len(PA_EVENT_ORDER)
    if len(transitions) != expected_keys:
        raise ValueError(f"PA transition table is incomplete: {len(transitions)} != {expected_keys}")
    return PAPriors(
        event_probabilities=probabilities,
        transitions=transitions,
        source=str(payload.get("source") or target),
    )


def _first_stat_split(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for block in payload.get("stats", []) or []:
        splits = block.get("splits") or []
        if splits:
            stat = splits[0].get("stat")
            if isinstance(stat, Mapping):
                return stat
    return {}


def _number(stat: Mapping[str, Any], key: str) -> float | None:
    value = stat.get(key)
    if value in (None, "", "-", "-.--", ".---", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _split_residual(residual: float, prior: np.ndarray) -> tuple[float, float]:
    reach = float(prior[PA_EVENT_INDEX["REACH"]])
    out = float(prior[PA_EVENT_INDEX["OUT"]])
    denominator = reach + out
    if residual <= 0 or denominator <= 0:
        return 0.0, max(0.0, residual)
    return residual * reach / denominator, residual * out / denominator


def hitter_profile_from_mlb_payload(
    payload: Mapping[str, Any] | None,
    *,
    prior: np.ndarray,
    source: str = "mlb_stats_api:season:hitting",
) -> PAEventProfile:
    stat = _first_stat_split(payload or {})
    pa = _number(stat, "plateAppearances") or 0.0
    hits = _number(stat, "hits") or 0.0
    doubles = _number(stat, "doubles") or 0.0
    triples = _number(stat, "triples") or 0.0
    homers = _number(stat, "homeRuns") or 0.0
    walks = _number(stat, "baseOnBalls") or 0.0
    hbp = _number(stat, "hitByPitch") or 0.0
    strikeouts = _number(stat, "strikeOuts") or 0.0
    singles = max(0.0, hits - doubles - triples - homers)
    known = strikeouts + walks + hbp + singles + doubles + triples + homers
    residual = max(0.0, pa - known)
    reach, outs = _split_residual(residual, prior)
    counts = (
        strikeouts,
        walks,
        hbp,
        singles,
        doubles,
        triples,
        homers,
        reach,
        outs,
    )
    return PAEventProfile(counts=counts, opportunities=pa, source=source)


def pitcher_profile_from_mlb_payload(
    payload: Mapping[str, Any] | None,
    *,
    prior: np.ndarray,
    source: str = "mlb_stats_api:season:pitching",
) -> PAEventProfile:
    stat = _first_stat_split(payload or {})
    batters = _number(stat, "battersFaced") or 0.0
    hits = _number(stat, "hits") or 0.0
    homers = _number(stat, "homeRuns") or 0.0
    walks = _number(stat, "baseOnBalls") or 0.0
    hbp = _number(stat, "hitBatsmen") or 0.0
    strikeouts = _number(stat, "strikeOuts") or 0.0

    non_hr_hits = max(0.0, hits - homers)
    hit_mix = np.asarray(
        [
            prior[PA_EVENT_INDEX["1B"]],
            prior[PA_EVENT_INDEX["2B"]],
            prior[PA_EVENT_INDEX["3B"]],
        ],
        dtype=float,
    )
    if hit_mix.sum() <= 0:
        hit_mix = np.asarray([0.75, 0.23, 0.02], dtype=float)
    hit_mix /= hit_mix.sum()
    singles, doubles, triples = non_hr_hits * hit_mix
    known = strikeouts + walks + hbp + hits
    residual = max(0.0, batters - known)
    reach, outs = _split_residual(residual, prior)
    counts = (
        strikeouts,
        walks,
        hbp,
        float(singles),
        float(doubles),
        float(triples),
        homers,
        reach,
        outs,
    )
    return PAEventProfile(counts=counts, opportunities=batters, source=source)


def combine_pa_event_profiles(
    profiles: Sequence[PAEventProfile],
    *,
    source: str,
) -> PAEventProfile:
    if not profiles:
        return PAEventProfile(
            counts=(0.0,) * len(PA_EVENT_ORDER),
            opportunities=0.0,
            source=source,
        )
    counts = np.sum(np.asarray([profile.counts for profile in profiles], dtype=float), axis=0)
    opportunities = float(sum(float(profile.opportunities) for profile in profiles))
    return PAEventProfile(
        counts=tuple(float(value) for value in counts),
        opportunities=opportunities,
        source=source,
    )


def matchup_event_probabilities(
    batter: PAEventProfile,
    pitcher: PAEventProfile,
    *,
    league_prior: np.ndarray,
    pitcher_prior_strength: float,
    batting_home: bool,
) -> np.ndarray:
    prior = np.asarray(league_prior, dtype=float)
    prior = np.clip(prior, 1e-9, None)
    prior /= prior.sum()
    batter_rates = batter.posterior_rates(prior, BATTER_PRIOR_PA)
    pitcher_rates = pitcher.posterior_rates(prior, pitcher_prior_strength)
    relative_batter = np.power(np.clip(batter_rates / prior, 1e-6, 1e6), BATTER_RELATIVE_RATE_EXPONENT)
    relative_pitcher = np.power(np.clip(pitcher_rates / prior, 1e-6, 1e6), PITCHER_RELATIVE_RATE_EXPONENT)
    probabilities = prior * relative_batter * relative_pitcher
    probabilities *= GLOBAL_EVENT_MULTIPLIER
    if batting_home:
        non_out = np.ones_like(probabilities)
        non_out[PA_EVENT_INDEX["K"]] = 1.0
        non_out[PA_EVENT_INDEX["OUT"]] = 1.0
        for name in ("BB", "HBP", "1B", "2B", "3B", "HR", "REACH"):
            non_out[PA_EVENT_INDEX[name]] = HOME_NON_OUT_MULTIPLIER
        probabilities *= non_out
    probabilities = np.clip(probabilities, 1e-12, None)
    return probabilities / probabilities.sum()


def _probability_tables(inputs: PAGameInputs, priors: PAPriors) -> tuple[np.ndarray, ...]:
    away_vs_home_starter = np.vstack(
        [
            matchup_event_probabilities(
                batter,
                inputs.home_starter,
                league_prior=priors.event_probabilities,
                pitcher_prior_strength=STARTER_PRIOR_PA,
                batting_home=False,
            )
            for batter in inputs.away_lineup
        ]
    )
    away_vs_home_bullpen = np.vstack(
        [
            matchup_event_probabilities(
                batter,
                inputs.home_bullpen,
                league_prior=priors.event_probabilities,
                pitcher_prior_strength=BULLPEN_PRIOR_PA,
                batting_home=False,
            )
            for batter in inputs.away_lineup
        ]
    )
    home_vs_away_starter = np.vstack(
        [
            matchup_event_probabilities(
                batter,
                inputs.away_starter,
                league_prior=priors.event_probabilities,
                pitcher_prior_strength=STARTER_PRIOR_PA,
                batting_home=True,
            )
            for batter in inputs.home_lineup
        ]
    )
    home_vs_away_bullpen = np.vstack(
        [
            matchup_event_probabilities(
                batter,
                inputs.away_bullpen,
                league_prior=priors.event_probabilities,
                pitcher_prior_strength=BULLPEN_PRIOR_PA,
                batting_home=True,
            )
            for batter in inputs.home_lineup
        ]
    )
    return tuple(np.cumsum(table, axis=1) for table in (
        away_vs_home_starter,
        away_vs_home_bullpen,
        home_vs_away_starter,
        home_vs_away_bullpen,
    ))


def simulate_pa_games(
    inputs: PAGameInputs,
    simulations: int,
    *,
    seed: int,
    priors: PAPriors | None = None,
    return_draws: bool = False,
    starter_workload_sd: float = 2.5,
    max_plate_appearances: int = 500,
) -> PASimulationResult:
    """Generate complete baseball games plate appearance by plate appearance.

    The function accepts no projected-score or expected-run input. Score and win
    probability are downstream outputs of the simulated PA sequence.
    """

    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if starter_workload_sd < 0:
        raise ValueError("starter_workload_sd cannot be negative")
    if max_plate_appearances < 80:
        raise ValueError("max_plate_appearances is implausibly small")

    active_priors = priors or load_pa_priors()
    away_start_cdf, away_pen_cdf, home_start_cdf, home_pen_cdf = _probability_tables(
        inputs, active_priors
    )
    rng = np.random.default_rng(int(seed))
    n = int(simulations)

    away_runs = np.zeros(n, dtype=np.int16)
    home_runs = np.zeros(n, dtype=np.int16)
    inning = np.ones(n, dtype=np.int16)
    half = np.zeros(n, dtype=np.int8)  # 0=top, 1=bottom
    outs = np.zeros(n, dtype=np.int8)
    bases = np.zeros(n, dtype=np.int8)
    away_batter = np.zeros(n, dtype=np.int8)
    home_batter = np.zeros(n, dtype=np.int8)
    home_pitcher_bf = np.zeros(n, dtype=np.int16)
    away_pitcher_bf = np.zeros(n, dtype=np.int16)
    completed = np.zeros(n, dtype=bool)
    reached_extras = np.zeros(n, dtype=bool)

    away_exit = np.clip(
        np.rint(rng.normal(inputs.away_starter_expected_batters, starter_workload_sd, n)),
        9,
        34,
    ).astype(np.int16)
    home_exit = np.clip(
        np.rint(rng.normal(inputs.home_starter_expected_batters, starter_workload_sd, n)),
        9,
        34,
    ).astype(np.int16)

    for _ in range(max_plate_appearances):
        active = np.flatnonzero(~completed)
        if len(active) == 0:
            break

        batting_home = half[active] == 1
        batter_index = np.where(batting_home, home_batter[active], away_batter[active])
        starter_active = np.where(
            batting_home,
            away_pitcher_bf[active] < away_exit[active],
            home_pitcher_bf[active] < home_exit[active],
        )

        event_index = np.empty(len(active), dtype=np.int8)
        uniforms = rng.random(len(active))
        for side_value in (0, 1):
            side_mask = batting_home == bool(side_value)
            if not np.any(side_mask):
                continue
            for starter_value in (False, True):
                pitcher_mask = starter_active == starter_value
                combined = side_mask & pitcher_mask
                if not np.any(combined):
                    continue
                for slot in range(9):
                    group = combined & (batter_index == slot)
                    if not np.any(group):
                        continue
                    if side_value == 0:
                        cdf = away_start_cdf[slot] if starter_value else away_pen_cdf[slot]
                    else:
                        cdf = home_start_cdf[slot] if starter_value else home_pen_cdf[slot]
                    selected_event = np.searchsorted(cdf, uniforms[group], side="right")
                    event_index[group] = np.minimum(selected_event, len(PA_EVENT_ORDER) - 1)

        # Every PA advances the batting order and the opposing pitcher's BF counter.
        away_indices = active[~batting_home]
        home_indices = active[batting_home]
        away_batter[away_indices] = (away_batter[away_indices] + 1) % 9
        home_batter[home_indices] = (home_batter[home_indices] + 1) % 9
        home_pitcher_bf[away_indices] += 1
        away_pitcher_bf[home_indices] += 1

        # Sample empirical 2024 base/out transitions for each current state and event.
        current_outs = outs[active].astype(int)
        current_bases = bases[active].astype(int)
        transition_uniforms = rng.random(len(active))
        outs_added = np.empty(len(active), dtype=np.int8)
        next_bases = np.empty(len(active), dtype=np.int8)
        runs_added = np.empty(len(active), dtype=np.int8)
        state_key = current_outs * 8 + current_bases
        for state in np.unique(state_key):
            state_mask = state_key == state
            state_outs = int(state // 8)
            state_bases = int(state % 8)
            for ev in np.unique(event_index[state_mask]):
                group = state_mask & (event_index == ev)
                if not np.any(group):
                    continue
                outcomes, cdf = active_priors.transitions[(state_outs, state_bases, int(ev))]
                selected = np.searchsorted(cdf, transition_uniforms[group], side="right")
                selected = np.minimum(selected, len(outcomes) - 1)
                chosen = outcomes[selected]
                outs_added[group] = chosen[:, 0]
                next_bases[group] = chosen[:, 1]
                runs_added[group] = chosen[:, 2]

        outs[active] = np.minimum(3, outs[active] + outs_added)
        bases[active] = next_bases
        away_runs[away_indices] += runs_added[~batting_home]
        home_runs[home_indices] += runs_added[batting_home]

        # Walk-off immediately after a home PA in the ninth or later.
        active_bottom = active[batting_home]
        if len(active_bottom):
            walkoff = (inning[active_bottom] >= 9) & (
                home_runs[active_bottom] > away_runs[active_bottom]
            )
            completed[active_bottom[walkoff]] = True

        # End half-innings for games not already completed by a walk-off.
        half_end = active[(outs[active] >= 3) & (~completed[active])]
        if len(half_end):
            was_bottom = half[half_end] == 1
            top_end = half_end[~was_bottom]
            bottom_end = half_end[was_bottom]

            if len(top_end):
                # In the ninth or later, a home team already leading after the top half
                # does not bat. Otherwise the bottom half begins normally.
                home_already_won = (inning[top_end] >= 9) & (
                    home_runs[top_end] > away_runs[top_end]
                )
                completed[top_end[home_already_won]] = True
                to_bottom = top_end[~home_already_won]
                if len(to_bottom):
                    half[to_bottom] = 1
                    outs[to_bottom] = 0
                    bases[to_bottom] = np.where(inning[to_bottom] >= 10, 2, 0).astype(np.int8)
                    reached_extras[to_bottom] |= inning[to_bottom] >= 10

            if len(bottom_end):
                regulation = inning[bottom_end] < 9
                regulation_end = bottom_end[regulation]
                if len(regulation_end):
                    inning[regulation_end] += 1
                    half[regulation_end] = 0
                    outs[regulation_end] = 0
                    bases[regulation_end] = 0

                late_end = bottom_end[~regulation]
                if len(late_end):
                    tied = away_runs[late_end] == home_runs[late_end]
                    completed[late_end[~tied]] = True
                    continuing = late_end[tied]
                    if len(continuing):
                        inning[continuing] += 1
                        half[continuing] = 0
                        outs[continuing] = 0
                        bases[continuing] = 2  # MLB automatic runner on second in extras.
                        reached_extras[continuing] = True

    if not np.all(completed):
        unfinished = int((~completed).sum())
        raise RuntimeError(
            f"PA simulator exceeded {max_plate_appearances} PAs with {unfinished} games unfinished"
        )
    if np.any(away_runs == home_runs):
        raise RuntimeError("complete PA simulations cannot finish tied")

    away_wins = away_runs > home_runs
    totals = away_runs.astype(np.int32) + home_runs.astype(np.int32)
    margins = np.abs(away_runs.astype(np.int32) - home_runs.astype(np.int32))
    return PASimulationResult(
        away_win_probability=float(away_wins.mean()),
        home_win_probability=float((~away_wins).mean()),
        mean_away_runs=float(away_runs.mean()),
        mean_home_runs=float(home_runs.mean()),
        median_away_runs=float(np.median(away_runs)),
        median_home_runs=float(np.median(home_runs)),
        extra_innings_probability=float(reached_extras.mean()),
        away_shutout_probability=float((away_runs == 0).mean()),
        home_shutout_probability=float((home_runs == 0).mean()),
        game_15_plus_probability=float((totals >= 15).mean()),
        five_plus_run_margin_probability=float((margins >= 5).mean()),
        one_run_game_probability=float((margins == 1).mean()),
        simulations=n,
        seed=int(seed),
        away_runs=away_runs.copy() if return_draws else None,
        home_runs=home_runs.copy() if return_draws else None,
    )
