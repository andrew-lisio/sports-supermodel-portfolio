from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .pricing import OutcomeProbability, fair_american_odds, playable_through_odds


TOTALS_MODEL_VERSION = "totals-v2-candidate.1"
TOTALS_MODEL_STATUS = "SHADOW_ONLY_NOT_PROMOTED"


@dataclass(frozen=True)
class TotalsModelConfig:
    """Candidate score distribution configuration.

    The candidate uses a shared run-environment gamma factor plus team-specific
    gamma variation. This yields positive score correlation and overdispersion while
    retaining the trained expected-run means. It is shadow-only until chronological
    calibration and holdout gates pass.
    """

    shared_environment_shape: float = 24.0
    team_dispersion_shape: float = 18.0
    minimum_expected_runs: float = 0.35
    maximum_expected_runs: float = 12.0
    random_seed: int = 20260804

    def __post_init__(self) -> None:
        if self.shared_environment_shape <= 0 or self.team_dispersion_shape <= 0:
            raise ValueError("dispersion shapes must be positive")
        if self.minimum_expected_runs <= 0:
            raise ValueError("minimum_expected_runs must be positive")
        if self.maximum_expected_runs <= self.minimum_expected_runs:
            raise ValueError("maximum_expected_runs must exceed minimum_expected_runs")


@dataclass(frozen=True)
class StarterWorkload:
    season_innings: float | None = None
    games_started: float | None = None
    rest_days: float | None = None
    recent_pitch_count: float | None = None
    role_cap_innings: float = 7.0

    def expected_innings(self) -> float:
        if self.season_innings is not None and self.games_started not in (None, 0):
            baseline = float(self.season_innings) / max(1.0, float(self.games_started))
        else:
            baseline = 5.25
        if self.rest_days is not None and float(self.rest_days) < 4:
            baseline -= 0.45
        if self.recent_pitch_count is not None and float(self.recent_pitch_count) >= 105:
            baseline -= 0.25
        return float(np.clip(baseline, 3.0, float(self.role_cap_innings)))


@dataclass(frozen=True)
class ScoreDraws:
    away_runs: np.ndarray
    home_runs: np.ndarray
    expected_away_runs: float
    expected_home_runs: float
    version: str = TOTALS_MODEL_VERSION
    status: str = TOTALS_MODEL_STATUS

    @property
    def simulations(self) -> int:
        return int(len(self.away_runs))


@dataclass(frozen=True)
class MarketFrontierPoint:
    market: str
    line: float
    selection: str
    win_probability: float
    push_probability: float
    fair_odds: int
    playable_through_odds: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TotalsValidationReport:
    status: str
    rows: int
    brier: float
    log_loss: float
    calibration_error: float
    version: str = TOTALS_MODEL_VERSION

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def blended_expected_runs(
    *,
    offense_runs_per_game: float,
    opposing_starter_ra9: float,
    opposing_bullpen_ra9: float,
    opposing_starter_expected_innings: float,
    park_weather_factor: float = 1.0,
    lineup_factor: float = 1.0,
) -> float:
    starter_innings = float(np.clip(opposing_starter_expected_innings, 0.0, 9.0))
    bullpen_innings = 9.0 - starter_innings
    pitching_ra9 = (
        float(opposing_starter_ra9) * starter_innings
        + float(opposing_bullpen_ra9) * bullpen_innings
    ) / 9.0
    mean = 0.5 * float(offense_runs_per_game) + 0.5 * pitching_ra9
    mean *= float(park_weather_factor) * float(lineup_factor)
    return float(np.clip(mean, 0.35, 12.0))


def simulate_totals_candidate(
    expected_away_runs: float,
    expected_home_runs: float,
    *,
    simulations: int = 100_000,
    config: TotalsModelConfig | None = None,
    rng: np.random.Generator | None = None,
) -> ScoreDraws:
    active = config or TotalsModelConfig()
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    away_mean = float(
        np.clip(expected_away_runs, active.minimum_expected_runs, active.maximum_expected_runs)
    )
    home_mean = float(
        np.clip(expected_home_runs, active.minimum_expected_runs, active.maximum_expected_runs)
    )
    generator = rng or np.random.default_rng(active.random_seed)
    shared = generator.gamma(
        shape=active.shared_environment_shape,
        scale=1.0 / active.shared_environment_shape,
        size=simulations,
    )
    away_noise = generator.gamma(
        shape=active.team_dispersion_shape,
        scale=1.0 / active.team_dispersion_shape,
        size=simulations,
    )
    home_noise = generator.gamma(
        shape=active.team_dispersion_shape,
        scale=1.0 / active.team_dispersion_shape,
        size=simulations,
    )
    away = generator.poisson(away_mean * shared * away_noise).astype(np.int16)
    home = generator.poisson(home_mean * shared * home_noise).astype(np.int16)
    return ScoreDraws(
        away_runs=away,
        home_runs=home,
        expected_away_runs=away_mean,
        expected_home_runs=home_mean,
    )


def probability_for_line(
    draws: ScoreDraws,
    *,
    market: str,
    line: float,
    selection: str,
    team: str | None = None,
) -> OutcomeProbability:
    market_key = str(market).strip().lower()
    selection_key = str(selection).strip().upper()
    if market_key == "game_total":
        values = draws.away_runs + draws.home_runs
    elif market_key == "away_team_total" or team == "away":
        values = draws.away_runs
    elif market_key == "home_team_total" or team == "home":
        values = draws.home_runs
    elif market_key == "run_line":
        if team == "away":
            adjusted = draws.away_runs.astype(float) + float(line)
            opponent = draws.home_runs.astype(float)
        elif team == "home":
            adjusted = draws.home_runs.astype(float) + float(line)
            opponent = draws.away_runs.astype(float)
        else:
            raise ValueError("run_line requires team='away' or team='home'")
        return OutcomeProbability(
            win=float(np.mean(adjusted > opponent)),
            push=float(np.mean(adjusted == opponent)),
        )
    else:
        raise ValueError(f"unsupported market: {market}")

    if selection_key == "OVER":
        wins = values > float(line)
    elif selection_key == "UNDER":
        wins = values < float(line)
    else:
        raise ValueError("selection must be OVER or UNDER")
    pushes = values == float(line)
    return OutcomeProbability(win=float(np.mean(wins)), push=float(np.mean(pushes)))


def build_line_frontier(
    draws: ScoreDraws,
    *,
    market: str = "game_total",
    lines: Iterable[float],
    team: str | None = None,
    minimum_required_roi: float = 0.02,
) -> tuple[MarketFrontierPoint, ...]:
    points: list[MarketFrontierPoint] = []
    for line in lines:
        for selection in ("OVER", "UNDER"):
            probability = probability_for_line(
                draws,
                market=market,
                line=float(line),
                selection=selection,
                team=team,
            )
            points.append(
                MarketFrontierPoint(
                    market=market,
                    line=float(line),
                    selection=selection,
                    win_probability=probability.win,
                    push_probability=probability.push,
                    fair_odds=fair_american_odds(probability),
                    playable_through_odds=playable_through_odds(
                        probability,
                        minimum_required_roi=minimum_required_roi,
                    ),
                )
            )
    return tuple(points)


def validate_probability_rows(
    rows: pd.DataFrame,
    *,
    probability_column: str = "over_probability",
    outcome_column: str = "over_result",
) -> TotalsValidationReport:
    if rows.empty:
        raise ValueError("validation rows cannot be empty")
    probabilities = np.clip(rows[probability_column].astype(float).to_numpy(), 1e-8, 1 - 1e-8)
    outcomes = rows[outcome_column].astype(float).to_numpy()
    if not np.isin(outcomes, [0.0, 1.0]).all():
        raise ValueError("outcomes must be binary after excluding pushes")
    brier = float(np.mean((probabilities - outcomes) ** 2))
    log_loss = float(
        -np.mean(outcomes * np.log(probabilities) + (1 - outcomes) * np.log(1 - probabilities))
    )
    bins = pd.cut(probabilities, bins=np.linspace(0, 1, 11), include_lowest=True)
    frame = pd.DataFrame({"p": probabilities, "y": outcomes, "bin": bins})
    grouped = frame.groupby("bin", observed=False).agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
    grouped = grouped.dropna()
    calibration_error = float(
        np.sum(np.abs(grouped["p"] - grouped["y"]) * grouped["n"]) / len(frame)
    )
    return TotalsValidationReport(
        status="PASS" if len(frame) >= 100 else "INSUFFICIENT_SAMPLE",
        rows=len(frame),
        brier=brier,
        log_loss=log_loss,
        calibration_error=calibration_error,
    )
