from pathlib import Path

from supermodel.mlb_v2 import build_pregame_features, load_team_logs, reconstruct_games


ROOT = Path(__file__).resolve().parents[1]


def test_feature_pipeline_has_no_empty_target():
    games = reconstruct_games(load_team_logs(ROOT / "data" / "2026"))
    features = build_pregame_features(games)
    assert len(features) > 1000
    assert features["a_win"].isin([0, 1]).all()
    assert not features[["team_a", "team_b", "date"]].isna().any().any()


def test_complete_seven_model_stack_is_available():
    from supermodel.mlb_v2 import make_models

    assert set(make_models()) == {
        "logistic",
        "random_forest",
        "neural_network",
        "elo_pyth",
        "xgboost",
        "lightgbm",
        "catboost",
    }
