from supermodel.mlb_v2 import build_pregame_features



def test_feature_pipeline_has_no_empty_target(synthetic_games):
    features = build_pregame_features(synthetic_games)
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
