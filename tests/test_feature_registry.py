from pathlib import Path

import pytest

from supermodel.feature_registry import (
    UnclassifiedFeatureError,
    feature_group_for,
    group_feature_names,
    validate_feature_groups,
)
from supermodel.mlb_v2 import (
    build_pregame_features,
    feature_columns,
    load_team_logs,
    reconstruct_games,
)

ROOT = Path(__file__).resolve().parents[1]


def test_known_features_map_to_expected_baseball_categories():
    assert feature_group_for("rf_pg_diff") == "offense"
    assert feature_group_for("last_blowout_loss_sum") == "recent_form"
    assert feature_group_for("starter_recent_ra_diff") == "starting_pitcher"
    assert feature_group_for("live_bullpen_fatigue") == "bullpen"
    assert feature_group_for("missing_lineup_wrc_plus") == "lineup"
    assert feature_group_for("live_weather_run_factor") == "weather"
    assert feature_group_for("missing_market_move") == "market"
    assert feature_group_for("team_a_is_home") == "home_field"


def test_current_model_features_are_covered_exactly_once():
    games = reconstruct_games(load_team_logs(ROOT / "data" / "2026"))
    features = build_pregame_features(games)
    names = feature_columns(features)

    validate_feature_groups(names)
    grouped = group_feature_names(names)
    assigned = [name for values in grouped.values() for name in values]

    assert len(assigned) == len(names)
    assert set(assigned) == set(names)
    assert all(values for values in grouped.values())


def test_registry_fails_closed_for_unknown_or_duplicate_features():
    with pytest.raises(UnclassifiedFeatureError):
        feature_group_for("future_magic_metric")
    with pytest.raises(ValueError, match="Duplicate model feature"):
        group_feature_names(["rf_pg_diff", "rf_pg_diff"])
