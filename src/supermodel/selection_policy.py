from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


SELECTION_POLICY_VERSION = "rc2-conflict-gate-v1"
SELECTION_POLICY_MODE = "PROVISIONAL_RECOMMENDATION_GATE"


@dataclass(frozen=True)
class SelectionPolicy:
    """Conservative eligibility policy for surfaced top picks.

    The raw ensemble prediction is preserved for measurement. This policy only decides
    whether a game can be promoted into the user-facing top-pick list when the weighted
    ensemble, component majority, and projected-score layer disagree.
    """

    minimum_pick_probability: float = 0.53
    minimum_model_overlap: int = 4
    score_conflict_margin_runs: float = 0.20
    version: str = SELECTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if not 0.5 <= self.minimum_pick_probability < 1.0:
            raise ValueError("minimum_pick_probability must be in [0.5, 1)")
        if self.minimum_model_overlap <= 0:
            raise ValueError("minimum_model_overlap must be positive")
        if self.score_conflict_margin_runs < 0.0:
            raise ValueError("score_conflict_margin_runs cannot be negative")


def _component_away_probabilities(row: pd.Series, away: str) -> list[float]:
    suffix = f"_{away}"
    columns = [
        column
        for column in row.index
        if str(column).startswith("p_") and str(column).endswith(suffix)
    ]
    return [float(row[column]) for column in sorted(columns)]


def apply_selection_policy(
    evaluations: pd.DataFrame,
    *,
    top_n: int,
    policy: SelectionPolicy | None = None,
) -> pd.DataFrame:
    """Annotate conflicts and choose top picks without changing model probabilities."""

    policy = policy or SelectionPolicy()
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if evaluations.empty:
        return evaluations.copy()

    frame = evaluations.copy()
    output: list[dict] = []
    for row in frame.to_dict("records"):
        away = str(row["away_team"])
        home = str(row["home_team"])
        pick = str(row["pick"])
        row_series = pd.Series(row)
        component_away = _component_away_probabilities(row_series, away)
        model_count = len(component_away) or int(row.get("model_count", 0))
        if component_away:
            away_votes = sum(value >= 0.5 for value in component_away)
            home_votes = model_count - away_votes
            component_pick = away if away_votes > home_votes else home
            component_overlap = max(away_votes, home_votes)
        else:
            # Compatibility for stored/legacy evaluation rows that omit component columns.
            component_pick = pick
            component_overlap = int(row.get("model_overlap", 0))
            away_votes = component_overlap if pick == away else max(0, model_count - component_overlap)
            home_votes = model_count - away_votes

        if row.get("simulated_away_runs") is not None and row.get("simulated_home_runs") is not None:
            away_runs = float(row["simulated_away_runs"])
            home_runs = float(row["simulated_home_runs"])
            score_pick = away if away_runs >= home_runs else home
            score_margin = abs(away_runs - home_runs)
        else:
            score_pick = pick
            score_margin = 0.0

        reasons: list[str] = []
        if component_pick != pick:
            reasons.append("COMPONENT_CONSENSUS_CONFLICT")
        if score_pick != pick and score_margin >= policy.score_conflict_margin_runs:
            reasons.append("PROJECTED_SCORE_CONFLICT")
        if float(row["pick_probability"]) < policy.minimum_pick_probability:
            reasons.append("LOW_PROBABILITY")
        if int(row.get("model_overlap", 0)) < policy.minimum_model_overlap:
            reasons.append("LOW_OVERLAP")

        eligible = not reasons
        row.update(
            {
                "component_consensus_pick": component_pick,
                "component_consensus_overlap": component_overlap,
                "component_away_votes": away_votes,
                "component_home_votes": home_votes,
                "projected_score_pick": score_pick,
                "projected_score_margin": score_margin,
                "ensemble_component_conflict": component_pick != pick,
                "ensemble_score_conflict": (
                    score_pick != pick
                    and score_margin >= policy.score_conflict_margin_runs
                ),
                "selection_policy_version": policy.version,
                "selection_policy_mode": SELECTION_POLICY_MODE,
                "selection_status": "ELIGIBLE" if eligible else "PASS",
                "selection_reasons": ";".join(reasons),
                "selection_reason_count": len(reasons),
                "eligible_for_top_pick": eligible,
            }
        )
        output.append(row)

    result = pd.DataFrame(output)
    result = result.sort_values(
        ["confidence_score", "pick_probability", "model_overlap"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["confidence_rank"] = np.arange(1, len(result) + 1)

    eligible_index = result.index[result["eligible_for_top_pick"]].tolist()
    selection_rank = pd.Series(pd.NA, index=result.index, dtype="Int64")
    for rank, index in enumerate(eligible_index, start=1):
        selection_rank.loc[index] = rank
    result["selection_rank"] = selection_rank
    result["is_top_pick"] = (
        result["eligible_for_top_pick"]
        & result["selection_rank"].notna()
        & (result["selection_rank"] <= int(top_n))
    )
    return result
