from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .advanced_features import CONTEXT_FEATURE_NAMES
from .feature_registry import feature_group_for
from .mlb_v2 import LIVE_FEATURES

FEATURE_AUTHORITY_SCHEMA_VERSION = 1
FEATURE_AUTHORITY_POLICY_VERSION = "rc3-feature-authority-v1"
MINIMUM_TRAINED_OBSERVATIONS = 100

# These are the only live fields that currently alter the score simulation directly.
DIRECT_SCORE_PROXY_FEATURES: frozenset[str] = frozenset(
    {"weather_run_factor", "park_run_factor"}
)

# Exact live-to-prospective-overlay relationships. Other context features are derived
# from richer PregameContext fields and are reported separately below.
LIVE_TO_CONTEXT_FEATURES: Mapping[str, tuple[str, ...]] = {
    "starter_fip": ("starter_fip_edge_home",),
    "starter_k_minus_bb": ("starter_kbb_edge_home",),
    "bullpen_fatigue": ("bullpen_fatigue_edge_home",),
    "closer_available": ("closer_availability_edge_home",),
    "travel_fatigue": ("travel_fatigue_edge_home",),
    "injury_war": ("injury_war_edge_home",),
    "lineup_confirmed": ("lineups_confirmed",),
}

CONTEXT_SOURCE_FAMILIES: Mapping[str, str] = {
    "starter_fip_edge_home": "starting_pitcher",
    "starter_kbb_edge_home": "starting_pitcher",
    "starter_whip_edge_home": "starting_pitcher",
    "lineup_ops_edge_home": "lineup",
    "lineup_woba_edge_home": "lineup",
    "lineup_k_rate_edge_home": "lineup",
    "lineup_coverage_min": "lineup",
    "bullpen_era_edge_home": "bullpen",
    "bullpen_fatigue_edge_home": "bullpen",
    "closer_availability_edge_home": "bullpen",
    "defense_fielding_edge_home": "defense",
    "defense_errors_edge_home": "defense",
    "travel_fatigue_edge_home": "rest_and_travel",
    "injury_war_edge_home": "injuries",
    "lineups_confirmed": "lineup",
    "starters_confirmed": "starting_pitcher",
}


@dataclass(frozen=True)
class LiveFeatureAuthority:
    feature: str
    feature_group: str
    historical_rows: int
    observed_rows: int
    observed_coverage: float
    unique_observed_values: int
    observed_variance: float | None
    winner_ensemble_authority: str
    score_model_authority: str
    adaptive_overlay_relationship: list[str]
    selection_policy_authority: str
    evidence_ledger_authority: str
    overall_status: str
    user_facing_claim: str


@dataclass(frozen=True)
class ContextFeatureAuthority:
    feature: str
    feature_group: str
    authority: str
    activation_requirement: str
    user_facing_claim: str


def _finite_variance(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(numeric) < 2:
        return None
    return float(numeric.var(ddof=0))


def _is_historically_trainable(*, observed_rows: int, unique_values: int, variance: float | None) -> bool:
    return (
        observed_rows >= MINIMUM_TRAINED_OBSERVATIONS
        and unique_values >= 2
        and variance is not None
        and variance > 0.0
    )


def _live_feature_record(historical_features: pd.DataFrame, name: str) -> LiveFeatureAuthority:
    live_column = f"live_{name}"
    missing_column = f"missing_{name}"
    row_count = int(len(historical_features))

    if live_column not in historical_features or missing_column not in historical_features:
        observed = pd.Series(dtype=float)
    else:
        missing = pd.to_numeric(historical_features[missing_column], errors="coerce").fillna(1.0)
        observed = historical_features.loc[missing < 0.5, live_column]

    observed_rows = int(len(observed))
    unique_values = int(pd.to_numeric(observed, errors="coerce").dropna().nunique())
    variance = _finite_variance(observed)
    historically_trainable = _is_historically_trainable(
        observed_rows=observed_rows,
        unique_values=unique_values,
        variance=variance,
    )

    if historically_trainable:
        winner_authority = "TRAINED_HISTORICAL_SIGNAL"
    else:
        winner_authority = "TRANSPORT_ONLY_UNTRAINED"

    if name in DIRECT_SCORE_PROXY_FEATURES:
        score_authority = "DIRECT_BOUNDED_SCORE_SIMULATION_PROXY"
    else:
        score_authority = "EXCLUDED_FROM_POISSON_SCORE_MODEL"

    overlay_relationship = list(LIVE_TO_CONTEXT_FEATURES.get(name, ()))
    has_overlay_relationship = bool(overlay_relationship)

    if historically_trainable:
        overall_status = "ACTIVE_TRAINED"
        claim = "Historically trained and eligible to change the winner ensemble."
    elif name in DIRECT_SCORE_PROXY_FEATURES:
        overall_status = "ACTIVE_DIRECT_PROXY"
        claim = (
            "Not historically trained in the winner ensemble; directly applies a bounded "
            "run-environment adjustment to the score simulation."
        )
    elif has_overlay_relationship:
        overall_status = "CAPTURED_PENDING_ADAPTIVE_AUTHORITY"
        claim = (
            "Captured for evidence and a related adaptive-overlay feature, but it does not "
            "change the base prediction unless the prospective overlay is ACTIVE."
        )
    else:
        overall_status = "CAPTURE_ONLY"
        claim = (
            "Captured for provenance/evidence only; it is not currently authorized to change "
            "the base winner or score prediction."
        )

    return LiveFeatureAuthority(
        feature=name,
        feature_group=feature_group_for(f"live_{name}"),
        historical_rows=row_count,
        observed_rows=observed_rows,
        observed_coverage=(observed_rows / row_count) if row_count else 0.0,
        unique_observed_values=unique_values,
        observed_variance=variance,
        winner_ensemble_authority=winner_authority,
        score_model_authority=score_authority,
        adaptive_overlay_relationship=overlay_relationship,
        selection_policy_authority="INDIRECT_OUTPUT_ONLY",
        evidence_ledger_authority="RECORDED_WITH_PROVENANCE",
        overall_status=overall_status,
        user_facing_claim=claim,
    )


def build_feature_authority_report(historical_features: pd.DataFrame) -> dict[str, Any]:
    """Return a fail-explicit map of which collected features can change predictions.

    The report distinguishes transport columns from historically trained signal. A live
    column being present in a model frame does not imply authority when all historical
    rows are missing/neutral. This is the central safeguard for RC3 development.
    """

    live_records = [_live_feature_record(historical_features, name) for name in LIVE_FEATURES]
    context_records = [
        ContextFeatureAuthority(
            feature=name,
            feature_group=CONTEXT_SOURCE_FAMILIES[name],
            authority="PROSPECTIVE_ADAPTIVE_OVERLAY_ONLY",
            activation_requirement=(
                "The overlay artifact must be ACTIVE after chronological prospective validation; "
                "PENDING or INACTIVE preserves the base V2.4 probability."
            ),
            user_facing_claim=(
                "Recorded prospectively and eligible for a bounded overlay only after its own "
                "chronological activation gate passes."
            ),
        )
        for name in CONTEXT_FEATURE_NAMES
    ]

    status_counts: dict[str, int] = {}
    for record in live_records:
        status_counts[record.overall_status] = status_counts.get(record.overall_status, 0) + 1

    trained_count = sum(
        record.winner_ensemble_authority == "TRAINED_HISTORICAL_SIGNAL"
        for record in live_records
    )
    direct_score_count = sum(
        record.score_model_authority == "DIRECT_BOUNDED_SCORE_SIMULATION_PROXY"
        for record in live_records
    )

    return {
        "schema_version": FEATURE_AUTHORITY_SCHEMA_VERSION,
        "policy_version": FEATURE_AUTHORITY_POLICY_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "historical_rows": int(len(historical_features)),
        "summary": {
            "live_features_collected": len(live_records),
            "live_features_historically_trained": trained_count,
            "live_features_with_direct_score_proxy_authority": direct_score_count,
            "prospective_context_features": len(context_records),
            "status_counts": status_counts,
            "base_prediction_disclosure": (
                "On the current historical contract, no advanced live field has historically "
                "trained winner-model authority unless the report explicitly says ACTIVE_TRAINED. "
                "Weather and park run factors are the only direct live score-simulation proxies."
            ),
        },
        "live_features": [asdict(record) for record in live_records],
        "prospective_context_features": [asdict(record) for record in context_records],
    }


def write_feature_authority_report(path: str | Path, report: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(target)
    return target
