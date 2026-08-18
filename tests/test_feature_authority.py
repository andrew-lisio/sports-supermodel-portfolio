from __future__ import annotations

import pandas as pd

from supermodel.feature_authority import (
    DIRECT_SCORE_PROXY_FEATURES,
    build_feature_authority_report,
)
from supermodel.mlb_v2 import LIVE_FEATURES, build_pregame_features


def test_current_contract_discloses_live_feature_authority_truthfully(synthetic_games):
    features = build_pregame_features(synthetic_games)
    report = build_feature_authority_report(features)

    assert report["summary"]["live_features_collected"] == len(LIVE_FEATURES)
    assert report["summary"]["live_features_historically_trained"] == 0
    assert report["summary"]["live_features_with_direct_score_proxy_authority"] == 2

    by_name = {row["feature"]: row for row in report["live_features"]}
    assert set(by_name) == set(LIVE_FEATURES)
    for name in DIRECT_SCORE_PROXY_FEATURES:
        assert by_name[name]["overall_status"] == "ACTIVE_DIRECT_PROXY"
        assert by_name[name]["score_model_authority"] == (
            "DIRECT_BOUNDED_SCORE_SIMULATION_PROXY"
        )
    assert by_name["bullpen_fatigue"]["overall_status"] == (
        "CAPTURED_PENDING_ADAPTIVE_AUTHORITY"
    )
    assert by_name["starter_velocity_trend"]["overall_status"] == "CAPTURE_ONLY"


def test_report_marks_sufficient_nonconstant_history_as_trained():
    rows = 120
    frame = pd.DataFrame(index=range(rows))
    for name in LIVE_FEATURES:
        frame[f"live_{name}"] = 0.0
        frame[f"missing_{name}"] = 1.0
    frame["live_starter_fip"] = [float(index % 7) for index in range(rows)]
    frame["missing_starter_fip"] = 0.0

    report = build_feature_authority_report(frame)
    by_name = {row["feature"]: row for row in report["live_features"]}
    assert by_name["starter_fip"]["winner_ensemble_authority"] == (
        "TRAINED_HISTORICAL_SIGNAL"
    )
    assert by_name["starter_fip"]["overall_status"] == "ACTIVE_TRAINED"
