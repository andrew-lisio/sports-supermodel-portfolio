from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

from .advanced_features import CONTEXT_FEATURE_NAMES, context_feature_vector, utc_now_text, write_json_atomic
from .evidence import ProspectiveEvidenceLedger
from .market import american_implied_probability, no_vig_probabilities, probability_to_american


ADAPTIVE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AdaptiveOverlayPolicy:
    minimum_training_games: int = 60
    minimum_validation_games: int = 20
    validation_fraction: float = 0.25
    regularization_c: float = 0.20
    maximum_logit_adjustment: float = 0.35
    maximum_log_loss_regression: float = 0.002

    def __post_init__(self) -> None:
        if self.minimum_training_games < 20:
            raise ValueError("minimum_training_games must be at least 20")
        if self.minimum_validation_games < 10:
            raise ValueError("minimum_validation_games must be at least 10")
        if not 0.1 <= self.validation_fraction <= 0.5:
            raise ValueError("validation_fraction must be in [0.1, 0.5]")
        if self.regularization_c <= 0:
            raise ValueError("regularization_c must be positive")
        if self.maximum_logit_adjustment <= 0:
            raise ValueError("maximum_logit_adjustment must be positive")


@dataclass(frozen=True)
class AdaptiveOverlayArtifact:
    status: str
    artifact_sha256: str
    generated_at_utc: str
    feature_names: tuple[str, ...]
    training_games: int
    validation_games: int
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    maximum_logit_adjustment: float
    metrics: Mapping[str, float | None]
    reason: str

    @property
    def active(self) -> bool:
        return self.status == "ACTIVE"

    def predict_home_probability(
        self,
        base_home_probability: float,
        context_features: Mapping[str, float] | None = None,
    ) -> float:
        base = float(np.clip(base_home_probability, 1e-6, 1 - 1e-6))
        if not self.active:
            return base
        context_features = context_features or {}
        raw = [math.log(base / (1.0 - base))]
        raw.extend(float(context_features.get(name, 0.0)) for name in CONTEXT_FEATURE_NAMES)
        values = np.asarray(raw, dtype=float)
        mean = np.asarray(self.scaler_mean, dtype=float)
        scale = np.asarray(self.scaler_scale, dtype=float)
        standardized = (values - mean) / np.where(scale == 0.0, 1.0, scale)
        fitted_logit = float(self.intercept + np.dot(np.asarray(self.coefficients), standardized))
        base_logit = raw[0]
        adjustment = float(
            np.clip(
                fitted_logit - base_logit,
                -self.maximum_logit_adjustment,
                self.maximum_logit_adjustment,
            )
        )
        adjusted_logit = base_logit + adjustment
        return float(1.0 / (1.0 + math.exp(-float(np.clip(adjusted_logit, -30, 30)))))


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _artifact_record_without_hash(
    *,
    status: str,
    feature_names: Sequence[str],
    training_games: int,
    validation_games: int,
    scaler_mean: Sequence[float],
    scaler_scale: Sequence[float],
    coefficients: Sequence[float],
    intercept: float,
    maximum_logit_adjustment: float,
    metrics: Mapping[str, float | None],
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": utc_now_text(),
        "feature_names": list(feature_names),
        "training_games": int(training_games),
        "validation_games": int(validation_games),
        "scaler_mean": [float(value) for value in scaler_mean],
        "scaler_scale": [float(value) for value in scaler_scale],
        "coefficients": [float(value) for value in coefficients],
        "intercept": float(intercept),
        "maximum_logit_adjustment": float(maximum_logit_adjustment),
        "metrics": dict(metrics),
        "reason": str(reason),
    }


def _finalize_artifact(record: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(record)
    body["artifact_sha256"] = sha256(_canonical_bytes(record)).hexdigest()
    return body


def _artifact_from_record(record: Mapping[str, Any]) -> AdaptiveOverlayArtifact:
    claimed = str(record.get("artifact_sha256", ""))
    without_hash = dict(record)
    without_hash.pop("artifact_sha256", None)
    actual = sha256(_canonical_bytes(without_hash)).hexdigest()
    if claimed != actual:
        raise ValueError("Adaptive overlay artifact SHA-256 mismatch")
    if int(record.get("schema_version", -1)) != ADAPTIVE_SCHEMA_VERSION:
        raise ValueError("Unsupported adaptive overlay schema")
    expected_names = ("base_home_logit", *CONTEXT_FEATURE_NAMES)
    names = tuple(str(value) for value in record.get("feature_names", []))
    if names != expected_names:
        raise ValueError("Adaptive overlay feature contract mismatch")
    return AdaptiveOverlayArtifact(
        status=str(record["status"]),
        artifact_sha256=claimed,
        generated_at_utc=str(record["generated_at_utc"]),
        feature_names=names,
        training_games=int(record["training_games"]),
        validation_games=int(record["validation_games"]),
        scaler_mean=tuple(float(value) for value in record["scaler_mean"]),
        scaler_scale=tuple(float(value) for value in record["scaler_scale"]),
        coefficients=tuple(float(value) for value in record["coefficients"]),
        intercept=float(record["intercept"]),
        maximum_logit_adjustment=float(record["maximum_logit_adjustment"]),
        metrics=dict(record.get("metrics") or {}),
        reason=str(record.get("reason") or ""),
    )


def load_adaptive_overlay(path: str | Path) -> AdaptiveOverlayArtifact | None:
    target = Path(path)
    if not target.exists():
        return None
    return _artifact_from_record(json.loads(target.read_text(encoding="utf-8")))


def _latest(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    candidates = [event for event in events if event["event_type"] == event_type]
    return max(candidates, key=lambda item: (item["recorded_at"], item["sequence"])) if candidates else None


def overlay_training_frame(ledger_path: str | Path) -> pd.DataFrame:
    events = ProspectiveEvidenceLedger(ledger_path).read(verify=True)
    by_game: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        by_game.setdefault(int(event["game_pk"]), []).append(event)
    rows: list[dict[str, Any]] = []
    for game_pk, game_events in by_game.items():
        prediction = _latest(game_events, "prediction")
        outcome = _latest(game_events, "outcome")
        if prediction is None or outcome is None:
            continue
        payload = prediction.get("payload") or {}
        base = payload.get("base_shadow_home_probability", payload.get("home_probability"))
        features = payload.get("context_features_home_orientation") or {}
        if base is None or not isinstance(features, Mapping):
            continue
        base_probability = float(base)
        if not 0.0 < base_probability < 1.0:
            continue
        row: dict[str, Any] = {
            "game_pk": game_pk,
            "recorded_at": prediction["recorded_at"],
            "base_home_probability": base_probability,
            "home_won": int(bool((outcome.get("payload") or {})["home_won"])),
        }
        row.update({name: float(features.get(name, 0.0)) for name in CONTEXT_FEATURE_NAMES})
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["recorded_at", "game_pk"]).reset_index(drop=True)


def _matrix(frame: pd.DataFrame) -> np.ndarray:
    base = np.clip(frame["base_home_probability"].to_numpy(dtype=float), 1e-6, 1 - 1e-6)
    base_logit = np.log(base / (1.0 - base))
    context = frame[list(CONTEXT_FEATURE_NAMES)].to_numpy(dtype=float)
    return np.column_stack([base_logit, context])


def fit_adaptive_overlay(
    ledger_path: str | Path,
    artifact_path: str | Path,
    *,
    policy: AdaptiveOverlayPolicy | None = None,
) -> AdaptiveOverlayArtifact:
    policy = policy or AdaptiveOverlayPolicy()
    frame = overlay_training_frame(ledger_path)
    feature_names = ("base_home_logit", *CONTEXT_FEATURE_NAMES)
    total = len(frame)
    if total < policy.minimum_training_games:
        record = _artifact_record_without_hash(
            status="PENDING",
            feature_names=feature_names,
            training_games=total,
            validation_games=0,
            scaler_mean=[0.0] * len(feature_names),
            scaler_scale=[1.0] * len(feature_names),
            coefficients=[0.0] * len(feature_names),
            intercept=0.0,
            maximum_logit_adjustment=policy.maximum_logit_adjustment,
            metrics={},
            reason=f"Collected {total} of {policy.minimum_training_games} graded games.",
        )
        final = _finalize_artifact(record)
        write_json_atomic(artifact_path, final)
        return _artifact_from_record(final)

    validation_n = max(policy.minimum_validation_games, int(round(total * policy.validation_fraction)))
    validation_n = min(validation_n, total // 2)
    split = total - validation_n
    train = frame.iloc[:split]
    validation = frame.iloc[split:]
    X_train = _matrix(train)
    X_validation = _matrix(validation)
    y_train = train["home_won"].to_numpy(dtype=int)
    y_validation = validation["home_won"].to_numpy(dtype=int)

    if len(np.unique(y_train)) < 2 or len(np.unique(y_validation)) < 2:
        record = _artifact_record_without_hash(
            status="INACTIVE",
            feature_names=feature_names,
            training_games=total,
            validation_games=validation_n,
            scaler_mean=[0.0] * len(feature_names),
            scaler_scale=[1.0] * len(feature_names),
            coefficients=[0.0] * len(feature_names),
            intercept=0.0,
            maximum_logit_adjustment=policy.maximum_logit_adjustment,
            metrics={},
            reason=(
                "Chronological train/validation slices require both outcomes; "
                "base shadow probability is preserved."
            ),
        )
        final = _finalize_artifact(record)
        write_json_atomic(artifact_path, final)
        return _artifact_from_record(final)

    scaler = StandardScaler().fit(X_train)
    model = LogisticRegression(
        C=policy.regularization_c,
        max_iter=2_000,
        random_state=20260727,
    ).fit(scaler.transform(X_train), y_train)
    raw_validation = model.predict_proba(scaler.transform(X_validation))[:, 1]
    base_validation = validation["base_home_probability"].to_numpy(dtype=float)

    base_brier = float(brier_score_loss(y_validation, base_validation))
    overlay_brier = float(brier_score_loss(y_validation, raw_validation))
    base_log_loss = float(log_loss(y_validation, base_validation, labels=[0, 1]))
    overlay_log_loss = float(log_loss(y_validation, raw_validation, labels=[0, 1]))
    active = (
        overlay_brier < base_brier
        and overlay_log_loss <= base_log_loss + policy.maximum_log_loss_regression
    )

    metrics = {
        "validation_base_brier": base_brier,
        "validation_overlay_brier": overlay_brier,
        "validation_brier_difference": overlay_brier - base_brier,
        "validation_base_log_loss": base_log_loss,
        "validation_overlay_log_loss": overlay_log_loss,
        "validation_log_loss_difference": overlay_log_loss - base_log_loss,
    }
    if active:
        final_scaler = StandardScaler().fit(_matrix(frame))
        final_model = LogisticRegression(
            C=policy.regularization_c,
            max_iter=2_000,
            random_state=20260727,
        ).fit(final_scaler.transform(_matrix(frame)), frame["home_won"].to_numpy(dtype=int))
        status = "ACTIVE"
        reason = "Chronological validation improved Brier without material log-loss regression."
        scaler_mean = final_scaler.mean_
        scaler_scale = final_scaler.scale_
        coefficients = final_model.coef_[0]
        intercept = float(final_model.intercept_[0])
    else:
        status = "INACTIVE"
        reason = "Chronological validation did not clear the activation gate; base shadow probability is preserved."
        scaler_mean = np.zeros(len(feature_names))
        scaler_scale = np.ones(len(feature_names))
        coefficients = np.zeros(len(feature_names))
        intercept = 0.0

    record = _artifact_record_without_hash(
        status=status,
        feature_names=feature_names,
        training_games=total,
        validation_games=validation_n,
        scaler_mean=scaler_mean,
        scaler_scale=scaler_scale,
        coefficients=coefficients,
        intercept=intercept,
        maximum_logit_adjustment=policy.maximum_logit_adjustment,
        metrics=metrics,
        reason=reason,
    )
    final = _finalize_artifact(record)
    write_json_atomic(artifact_path, final)
    return _artifact_from_record(final)


def pending_overlay(policy: AdaptiveOverlayPolicy | None = None) -> AdaptiveOverlayArtifact:
    policy = policy or AdaptiveOverlayPolicy()
    names = ("base_home_logit", *CONTEXT_FEATURE_NAMES)
    record = _artifact_record_without_hash(
        status="PENDING",
        feature_names=names,
        training_games=0,
        validation_games=0,
        scaler_mean=[0.0] * len(names),
        scaler_scale=[1.0] * len(names),
        coefficients=[0.0] * len(names),
        intercept=0.0,
        maximum_logit_adjustment=policy.maximum_logit_adjustment,
        metrics={},
        reason="No graded prospective games are available.",
    )
    return _artifact_from_record(_finalize_artifact(record))


def apply_overlay_to_evaluation(
    evaluation: pd.DataFrame,
    *,
    contexts_by_game_pk: Mapping[int, Any],
    overlay: AdaptiveOverlayArtifact,
    top_n: int,
) -> pd.DataFrame:
    frame = evaluation.copy()
    if frame.empty:
        return frame
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        game_pk = int(row["game_pk"])
        context = contexts_by_game_pk[game_pk]
        vector = context_feature_vector(context)
        base_home = float(row["home_probability"])
        adjusted_home = overlay.predict_home_probability(base_home, vector)
        adjusted_away = 1.0 - adjusted_home
        away = str(row["away_team"])
        home = str(row["home_team"])
        pick = away if adjusted_away >= adjusted_home else home
        pick_is_away = pick == away
        pick_probability = adjusted_away if pick_is_away else adjusted_home
        pick_odds = int(row["away_odds"] if pick_is_away else row["home_odds"])
        away_market, home_market = no_vig_probabilities(int(row["away_odds"]), int(row["home_odds"]))
        pick_no_vig = away_market if pick_is_away else home_market
        component_columns = [
            name for name in row
            if name.startswith("p_") and name.endswith(f"_{away}")
        ]
        component_away = [float(row[name]) for name in component_columns]
        overlap = sum((value >= 0.5) if pick_is_away else (value < 0.5) for value in component_away)
        model_count = len(component_away) or int(row.get("model_count", 0))
        probability_strength = 2.0 * abs(pick_probability - 0.5)
        overlap_rate = overlap / model_count if model_count else 0.0
        row.update(
            {
                "base_shadow_away_probability": float(row["away_probability"]),
                "base_shadow_home_probability": base_home,
                "away_probability": adjusted_away,
                "home_probability": adjusted_home,
                "pick": pick,
                "pick_probability": pick_probability,
                "pick_odds": pick_odds,
                "model_overlap": overlap,
                "confidence_score": 0.70 * probability_strength + 0.30 * overlap_rate,
                "no_vig_pick_probability": pick_no_vig,
                "break_even_probability": american_implied_probability(pick_odds),
                "edge_vs_no_vig": pick_probability - pick_no_vig,
                "edge_vs_break_even": pick_probability - american_implied_probability(pick_odds),
                "fair_odds": probability_to_american(pick_probability),
                "adaptive_overlay_status": overlay.status,
                "adaptive_overlay_sha256": overlay.artifact_sha256,
                "adaptive_overlay_training_games": overlay.training_games,
                "adaptive_overlay_adjustment_home": adjusted_home - base_home,
                "context_features_home_orientation": vector,
            }
        )
        rows.append(row)
    result = pd.DataFrame(rows).sort_values(
        ["confidence_score", "pick_probability", "model_overlap"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    result["confidence_rank"] = np.arange(1, len(result) + 1)
    result["is_top_pick"] = result["confidence_rank"] <= int(top_n)
    return result
