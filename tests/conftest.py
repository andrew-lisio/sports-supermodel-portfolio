from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest


@pytest.fixture(scope="session")
def synthetic_games() -> pd.DataFrame:
    """Deterministic >1,000-game fixture with no external/private dataset dependency."""

    teams = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    pairings = [
        [(0, 1), (2, 3), (4, 5), (6, 7)],
        [(0, 2), (1, 4), (3, 6), (5, 7)],
        [(0, 3), (1, 5), (2, 7), (4, 6)],
        [(0, 4), (1, 6), (2, 5), (3, 7)],
        [(0, 5), (1, 7), (2, 6), (3, 4)],
        [(0, 6), (1, 3), (2, 4), (5, 7)],
        [(0, 7), (1, 2), (3, 5), (4, 6)],
    ]
    start = date(2024, 3, 20)
    rows: list[dict[str, object]] = []
    game_pk = 900_000

    # 276 dates x 4 games/date = 1,104 canonical games.
    for day_index in range(276):
        game_date = pd.Timestamp(start + timedelta(days=day_index))
        for slot, (left, right) in enumerate(pairings[day_index % len(pairings)]):
            a, b = sorted((teams[left], teams[right]))
            seed = day_index * 11 + slot * 7 + left * 3 + right
            a_runs = float((seed % 8) + 1)
            b_runs = float(((seed * 3 + 2) % 8) + 1)
            if a_runs == b_runs:
                b_runs += 1.0
            rows.append(
                {
                    "date": game_date,
                    "game_pk": game_pk,
                    "team_a": a,
                    "team_b": b,
                    "a_runs": a_runs,
                    "b_runs": b_runs,
                    "a_win": int(a_runs > b_runs),
                    "a_starter": f"{a}_SP_{day_index % 5}",
                    "b_starter": f"{b}_SP_{(day_index + slot) % 5}",
                    "team_a_is_home": float((day_index + slot) % 2),
                    "missing_home_away": 0.0,
                }
            )
            game_pk += 1

    return pd.DataFrame(rows).sort_values(["date", "team_a", "team_b"]).reset_index(drop=True)
