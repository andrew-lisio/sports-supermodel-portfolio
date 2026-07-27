from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from supermodel.adaptive_overlay import (
    AdaptiveOverlayPolicy,
    apply_overlay_to_evaluation,
    fit_adaptive_overlay,
    load_adaptive_overlay,
)
from supermodel.advanced_features import CONTEXT_FEATURE_NAMES
from supermodel.evidence import ProspectiveEvidenceLedger
from supermodel.workflow import combine_production_and_shadow


def _append_training_game(ledger, game_pk: int, signal: float, home_won: int) -> None:
    start = datetime(2030, 7, 1, 23, tzinfo=timezone.utc) + timedelta(days=game_pk - 1)
    vector = {name: 0.0 for name in CONTEXT_FEATURE_NAMES}
    vector["lineup_ops_edge_home"] = signal
    ledger.append(
        event_type="prediction",
        game_pk=game_pk,
        recorded_at=start - timedelta(hours=3),
        scheduled_start=start,
        source="test",
        payload={
            "away_team": "AAA",
            "home_team": "BBB",
            "home_probability": 0.5,
            "away_probability": 0.5,
            "model_version": "2.4-test",
            "base_shadow_home_probability": 0.5,
            "context_features_home_orientation": vector,
        },
    )
    ledger.append(
        event_type="outcome",
        game_pk=game_pk,
        recorded_at=start + timedelta(hours=4),
        scheduled_start=start,
        source="test",
        payload={"home_won": home_won},
    )


def test_overlay_stays_pending_without_enough_graded_games(tmp_path):
    artifact_path = tmp_path / "overlay.json"
    overlay = fit_adaptive_overlay(tmp_path / "missing.jsonl", artifact_path)
    assert overlay.status == "PENDING"
    assert overlay.training_games == 0
    assert artifact_path.exists()
    assert load_adaptive_overlay(artifact_path).artifact_sha256 == overlay.artifact_sha256


def test_overlay_activates_only_after_chronological_validation_improves(tmp_path):
    ledger = ProspectiveEvidenceLedger(tmp_path / "prospective.jsonl")
    for game_pk in range(1, 81):
        signal = 1.0 if game_pk % 2 else -1.0
        _append_training_game(ledger, game_pk, signal, int(signal > 0))

    path = tmp_path / "overlay.json"
    overlay = fit_adaptive_overlay(
        ledger.path,
        path,
        policy=AdaptiveOverlayPolicy(
            minimum_training_games=60,
            minimum_validation_games=20,
            validation_fraction=0.25,
        ),
    )
    assert overlay.status == "ACTIVE"
    assert overlay.training_games == 80
    assert overlay.metrics["validation_brier_difference"] < 0
    assert overlay.predict_home_probability(0.5, {"lineup_ops_edge_home": 1.0}) > 0.5
    assert overlay.predict_home_probability(0.5, {"lineup_ops_edge_home": -1.0}) < 0.5


def test_overlay_application_and_production_shadow_combination_are_versioned(tmp_path):
    overlay = fit_adaptive_overlay(
        tmp_path / "missing.jsonl",
        tmp_path / "overlay.json",
        policy=AdaptiveOverlayPolicy(minimum_training_games=60),
    )
    base = pd.DataFrame([{
        "game_date": "2030-07-01",
        "game_pk": 1,
        "away_team": "AAA",
        "home_team": "BBB",
        "away_odds": 110,
        "home_odds": -120,
        "pick": "BBB",
        "pick_odds": -120,
        "pick_probability": 0.55,
        "away_probability": 0.45,
        "home_probability": 0.55,
        "model_overlap": 5,
        "model_count": 7,
        "confidence_score": 0.3,
        "confidence_rank": 1,
        "simulations": 100_000,
    }])
    context = SimpleNamespace(**{
        "game_pk": 1,
        **{name: None for name in [
            "home_starter_fip", "away_starter_fip", "home_k_minus_bb", "away_k_minus_bb",
            "home_starter_whip", "away_starter_whip", "home_lineup_ops", "away_lineup_ops",
            "home_lineup_woba_proxy", "away_lineup_woba_proxy", "home_lineup_k_rate",
            "away_lineup_k_rate", "home_lineup_stats_coverage", "away_lineup_stats_coverage",
            "home_bullpen_era_proxy", "away_bullpen_era_proxy", "home_bullpen_fatigue",
            "away_bullpen_fatigue", "home_closer_available", "away_closer_available",
            "home_defense_fielding_pct", "away_defense_fielding_pct",
            "home_defense_errors_per_game", "away_defense_errors_per_game",
            "home_travel_fatigue", "away_travel_fatigue", "home_injury_war", "away_injury_war",
        ]},
        "lineups_confirmed": False,
        "away_probable_pitcher_id": None,
        "home_probable_pitcher_id": None,
    })
    shadow = apply_overlay_to_evaluation(base, contexts_by_game_pk={1: context}, overlay=overlay, top_n=1)
    combined = combine_production_and_shadow(base, shadow)
    assert combined.iloc[0].pick == "BBB"
    assert combined.iloc[0].shadow_pick == "BBB"
    assert combined.iloc[0].production_model_version == "2.3.3"
    assert combined.iloc[0].shadow_adaptive_overlay_status == "PENDING"
    assert bool(combined.iloc[0].production_shadow_disagree) is False
