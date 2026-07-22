from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass
class InningInputs:
    away_starter_ra9: float
    home_starter_ra9: float
    away_bullpen_ra9: float
    home_bullpen_ra9: float
    away_offense_factor: float = 1.0
    home_offense_factor: float = 1.0
    park_weather_factor: float = 1.0
    away_starter_expected_innings: float = 5.5
    home_starter_expected_innings: float = 5.5


def simulate_innings(inputs: InningInputs, n: int = 100_000, seed: int = 20260720) -> dict[str, float]:
    """Nine-inning starter/bullpen simulation with score-dependent extra innings.

    The starter-to-bullpen transition is randomized around expected innings. A shared
    gamma environment term allows offensive conditions to affect both teams. This is
    more realistic than drawing one final score from a fixed independent Poisson pair,
    while remaining fast enough for slate-wide repeated runs.
    """
    rng = np.random.default_rng(seed)
    away = np.zeros(n, dtype=int)
    home = np.zeros(n, dtype=int)
    away_exit = np.clip(rng.normal(inputs.away_starter_expected_innings, 0.8, n), 3, 8)
    home_exit = np.clip(rng.normal(inputs.home_starter_expected_innings, 0.8, n), 3, 8)
    env = rng.gamma(20.0, 1/20.0, n) * inputs.park_weather_factor
    for inning in range(1, 10):
        # Away offense faces the home pitcher; home offense faces the away pitcher.
        home_pitch_ra9 = np.where(inning <= home_exit, inputs.home_starter_ra9, inputs.home_bullpen_ra9)
        away_pitch_ra9 = np.where(inning <= away_exit, inputs.away_starter_ra9, inputs.away_bullpen_ra9)
        away += rng.poisson(np.clip(home_pitch_ra9/9 * inputs.away_offense_factor * env, 0.02, 1.8))
        home += rng.poisson(np.clip(away_pitch_ra9/9 * inputs.home_offense_factor * env, 0.02, 1.8))
    tied = away == home
    # Extra innings: repeat a modestly elevated run process until resolved, capped for speed.
    for _ in range(6):
        if not tied.any():
            break
        ix = np.where(tied)[0]
        away[ix] += rng.poisson(0.55 * inputs.away_offense_factor, len(ix))
        home[ix] += rng.poisson(0.55 * inputs.home_offense_factor, len(ix))
        tied = away == home
    if tied.any():
        ix = np.where(tied)[0]
        home[ix] += rng.binomial(1, 0.5, len(ix))
        away[ix] += (home[ix] == away[ix]).astype(int)
    return {
        'away_win_probability': float((away>home).mean()),
        'home_win_probability': float((home>away).mean()),
        'mean_away_runs': float(away.mean()),
        'mean_home_runs': float(home.mean()),
        'over_8_5_probability': float(((away+home)>8.5).mean()),
    }
