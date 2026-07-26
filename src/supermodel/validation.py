from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from .mlb_v2 import RANDOM_SEED, V2Ensemble


# Phase 3 is the first V2.4 phase that changes the predictive feature contract.
# Removing these fields recreates the V2.3.3 winner-model input contract while
# keeping the same games, labels, folds, model code, and information cutoff.
V23_BASELINE_EXCLUDED_FEATURES: tuple[str, ...] = (
    "win3_diff",
    "rf3_diff",
    "rf3_sum",
    "ra3_diff",
    "ra3_sum",
    "rd3_diff",
    "form_win_momentum_diff",
    "form_rf_momentum_diff",
    "form_ra_momentum_diff",
    "form_rd_momentum_diff",
)


@dataclass(frozen=True)
class ValidationWindow:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    role: str = "development"
    minimum_training_games: int = 150

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Validation window {self.name!r} ends before it starts")
        if self.role not in {"development", "holdout"}:
            raise ValueError(f"Unsupported validation role: {self.role}")
        if self.minimum_training_games <= 0:
            raise ValueError("minimum_training_games must be positive")


@dataclass(frozen=True)
class ValidationPlan:
    development_windows: tuple[ValidationWindow, ...]
    holdout_window: ValidationWindow | None
    calibration_bins: int = 10
    bootstrap_iterations: int = 2_000
    random_seed: int = RANDOM_SEED


def _timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"Invalid validation date: {value!r}")
    return timestamp.normalize()


def load_validation_plan(path: str | Path) -> ValidationPlan:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = document.get("defaults", {})
    minimum_training_games = int(defaults.get("minimum_training_games", 150))

    development: list[ValidationWindow] = []
    for index, raw in enumerate(document.get("development_windows", []), start=1):
        development.append(
            ValidationWindow(
                name=str(raw.get("name", f"development_{index}")),
                start=_timestamp(raw["start"]),
                end=_timestamp(raw["end"]),
                role="development",
                minimum_training_games=int(
                    raw.get("minimum_training_games", minimum_training_games)
                ),
            )
        )
    if not development:
        raise ValueError("At least one development window is required")

    holdout_raw = document.get("holdout")
    holdout = None
    if holdout_raw:
        holdout = ValidationWindow(
            name=str(holdout_raw.get("name", "final_holdout")),
            start=_timestamp(holdout_raw["start"]),
            end=_timestamp(holdout_raw["end"]),
            role="holdout",
            minimum_training_games=int(
                holdout_raw.get("minimum_training_games", minimum_training_games)
            ),
        )

    return ValidationPlan(
        development_windows=tuple(development),
        holdout_window=holdout,
        calibration_bins=int(document.get("calibration_bins", 10)),
        bootstrap_iterations=int(document.get("bootstrap_iterations", 2_000)),
        random_seed=int(document.get("random_seed", RANDOM_SEED)),
    )


def freeze_v23_feature_contract(features: pd.DataFrame) -> pd.DataFrame:
    """Return a copy using the frozen V2.3.3 predictive feature contract."""

    return features.drop(
        columns=[name for name in V23_BASELINE_EXCLUDED_FEATURES if name in features.columns]
    ).copy()


def _clean_probability_inputs(
    y: Iterable[float] | pd.Series,
    p: Iterable[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    y_array = np.asarray(list(y) if not isinstance(y, pd.Series) else y.to_numpy(), dtype=float)
    p_array = np.asarray(p, dtype=float)
    if y_array.shape[0] != p_array.shape[0]:
        raise ValueError("Outcome and probability arrays must have the same length")
    total = int(y_array.shape[0])
    valid = np.isfinite(y_array) & np.isfinite(p_array)
    y_valid = y_array[valid].astype(int)
    p_valid = np.clip(p_array[valid], 1e-6, 1 - 1e-6)
    if y_valid.size and not np.isin(y_valid, [0, 1]).all():
        raise ValueError("Outcomes must be binary")
    return y_valid, p_valid, total


def calibration_table(
    y: Iterable[float] | pd.Series,
    p: Iterable[float] | np.ndarray,
    *,
    bins: int = 10,
) -> pd.DataFrame:
    if bins < 2:
        raise ValueError("bins must be at least 2")
    y_valid, p_valid, _ = _clean_probability_inputs(y, p)
    edges = np.linspace(0.0, 1.0, bins + 1)
    if y_valid.size == 0:
        return pd.DataFrame(
            columns=[
                "bin",
                "lower",
                "upper",
                "n",
                "mean_probability",
                "observed_rate",
                "absolute_gap",
            ]
        )
    bin_index = np.minimum(np.searchsorted(edges, p_valid, side="right") - 1, bins - 1)
    rows: list[dict[str, float | int]] = []
    for index in range(bins):
        mask = bin_index == index
        if not mask.any():
            continue
        mean_probability = float(p_valid[mask].mean())
        observed_rate = float(y_valid[mask].mean())
        rows.append(
            {
                "bin": index + 1,
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "n": int(mask.sum()),
                "mean_probability": mean_probability,
                "observed_rate": observed_rate,
                "absolute_gap": abs(mean_probability - observed_rate),
            }
        )
    return pd.DataFrame(rows)


def probability_metrics(
    y: Iterable[float] | pd.Series,
    p: Iterable[float] | np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, float | int]:
    y_valid, p_valid, total = _clean_probability_inputs(y, p)
    if y_valid.size == 0:
        return {
            "n_total": total,
            "n": 0,
            "coverage": 0.0,
            "accuracy": float("nan"),
            "brier": float("nan"),
            "log_loss": float("nan"),
            "auc": float("nan"),
            "ece": float("nan"),
            "mce": float("nan"),
            "mean_probability": float("nan"),
            "observed_rate": float("nan"),
        }

    table = calibration_table(y_valid, p_valid, bins=bins)
    weights = table["n"].to_numpy(dtype=float) / float(y_valid.size)
    gaps = table["absolute_gap"].to_numpy(dtype=float)
    return {
        "n_total": total,
        "n": int(y_valid.size),
        "coverage": float(y_valid.size / total) if total else 0.0,
        "accuracy": float(accuracy_score(y_valid, p_valid >= 0.5)),
        "brier": float(brier_score_loss(y_valid, p_valid)),
        "log_loss": float(log_loss(y_valid, p_valid, labels=[0, 1])),
        "auc": (
            float(roc_auc_score(y_valid, p_valid))
            if len(np.unique(y_valid)) > 1
            else float("nan")
        ),
        "ece": float(np.sum(weights * gaps)),
        "mce": float(gaps.max()) if gaps.size else float("nan"),
        "mean_probability": float(p_valid.mean()),
        "observed_rate": float(y_valid.mean()),
    }


def _metric_differences(
    y: np.ndarray,
    baseline: np.ndarray,
    candidate: np.ndarray,
) -> dict[str, float]:
    baseline_metrics = probability_metrics(y, baseline)
    candidate_metrics = probability_metrics(y, candidate)
    return {
        "accuracy": float(candidate_metrics["accuracy"] - baseline_metrics["accuracy"]),
        "brier": float(candidate_metrics["brier"] - baseline_metrics["brier"]),
        "log_loss": float(candidate_metrics["log_loss"] - baseline_metrics["log_loss"]),
        "auc": float(candidate_metrics["auc"] - baseline_metrics["auc"]),
    }


def paired_bootstrap_differences(
    y: Iterable[float] | pd.Series,
    baseline_probability: Iterable[float] | np.ndarray,
    candidate_probability: Iterable[float] | np.ndarray,
    *,
    iterations: int = 2_000,
    seed: int = RANDOM_SEED,
) -> dict[str, dict[str, float | list[float] | int]]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    y_array = np.asarray(y, dtype=int)
    baseline = np.asarray(baseline_probability, dtype=float)
    candidate = np.asarray(candidate_probability, dtype=float)
    if not (len(y_array) == len(baseline) == len(candidate)):
        raise ValueError("Paired bootstrap inputs must have equal length")
    valid = np.isfinite(y_array) & np.isfinite(baseline) & np.isfinite(candidate)
    y_array = y_array[valid]
    baseline = np.clip(baseline[valid], 1e-6, 1 - 1e-6)
    candidate = np.clip(candidate[valid], 1e-6, 1 - 1e-6)
    if y_array.size == 0:
        raise ValueError("Paired bootstrap requires at least one matched prediction")

    point = _metric_differences(y_array, baseline, candidate)
    samples: dict[str, list[float]] = {name: [] for name in point}
    rng = np.random.default_rng(seed)
    for _ in range(iterations):
        index = rng.integers(0, y_array.size, size=y_array.size)
        y_sample = y_array[index]
        baseline_sample = baseline[index]
        candidate_sample = candidate[index]
        differences = _metric_differences(y_sample, baseline_sample, candidate_sample)
        for name, value in differences.items():
            if np.isfinite(value):
                samples[name].append(float(value))

    result: dict[str, dict[str, float | list[float] | int]] = {}
    for name, point_value in point.items():
        values = np.asarray(samples[name], dtype=float)
        ci = (
            [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
            if values.size
            else [float("nan"), float("nan")]
        )
        result[name] = {
            "point": float(point_value),
            "ci95": ci,
            "bootstrap_samples": int(values.size),
        }
    return result


def _prediction_identity_columns(frame: pd.DataFrame) -> list[str]:
    preferred = [
        "date",
        "game_pk",
        "team_a",
        "team_b",
        "away_team",
        "home_team",
        "a_win",
        "a_runs",
        "b_runs",
        "team_a_is_home",
        "missing_home_away",
        "lineups_confirmed",
    ]
    return [name for name in preferred if name in frame.columns]


def _fold_metric_row(
    *,
    window: ValidationWindow,
    train_n: int,
    validation_n: int,
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    baseline_runtime_seconds: float,
    candidate_runtime_seconds: float,
) -> dict[str, Any]:
    return {
        "window": window.name,
        "role": window.role,
        "window_start": window.start.date().isoformat(),
        "window_end": window.end.date().isoformat(),
        "train_n": train_n,
        "validation_n": validation_n,
        "baseline_runtime_seconds": baseline_runtime_seconds,
        "candidate_runtime_seconds": candidate_runtime_seconds,
        **{f"baseline_{key}": value for key, value in baseline_metrics.items()},
        **{f"candidate_{key}": value for key, value in candidate_metrics.items()},
    }


def _assert_matched_feature_rows(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    context: str,
) -> None:
    identity = [
        column
        for column in ["date", "game_pk", "team_a", "team_b", "a_win", "a_runs", "b_runs"]
        if column in baseline.columns and column in candidate.columns
    ]
    required = {"date", "team_a", "team_b", "a_win"}
    if not required.issubset(identity):
        raise ValueError(f"{context}: feature frames lack required identity columns")
    left = baseline[identity].reset_index(drop=True)
    right = candidate[identity].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
    except AssertionError as exc:
        raise ValueError(
            f"{context}: V2.3.3 and V2.4 feature frames do not contain identical games"
        ) from exc


def run_matched_walk_forward(
    features: pd.DataFrame,
    windows: Iterable[ValidationWindow],
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
    calibration_bins: int = 10,
    baseline_features: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run V2.3.3 and V2.4 on identical chronological validation games.

    ``features`` contains the active V2.4 candidate contract. When
    ``baseline_features`` is supplied, it must contain the same games built with
    the frozen V2.3.3 state-update settings (including its 0.18 EWM alpha). The
    baseline feature-column contract is then frozen separately. Supplying no
    baseline frame retains backward compatibility for tests and older callers.
    """

    if "date" not in features or "a_win" not in features:
        raise ValueError("features must contain date and a_win columns")
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["date", "team_a", "team_b"]).reset_index(drop=True)

    baseline_frame = (baseline_features if baseline_features is not None else features).copy()
    if "date" not in baseline_frame or "a_win" not in baseline_frame:
        raise ValueError("baseline_features must contain date and a_win columns")
    baseline_frame["date"] = pd.to_datetime(baseline_frame["date"])
    baseline_frame = baseline_frame.sort_values(
        ["date", "team_a", "team_b"]
    ).reset_index(drop=True)

    predictions: list[pd.DataFrame] = []
    folds: list[dict[str, Any]] = []
    for window in windows:
        train = frame[frame["date"] < window.start].copy()
        validation = frame[
            (frame["date"] >= window.start) & (frame["date"] <= window.end)
        ].copy()
        baseline_train_source = baseline_frame[baseline_frame["date"] < window.start].copy()
        baseline_validation_source = baseline_frame[
            (baseline_frame["date"] >= window.start)
            & (baseline_frame["date"] <= window.end)
        ].copy()
        if len(train) < window.minimum_training_games or validation.empty:
            folds.append(
                {
                    "window": window.name,
                    "role": window.role,
                    "window_start": window.start.date().isoformat(),
                    "window_end": window.end.date().isoformat(),
                    "train_n": len(train),
                    "validation_n": len(validation),
                    "status": "skipped",
                    "reason": (
                        "insufficient_training_games"
                        if len(train) < window.minimum_training_games
                        else "no_validation_games"
                    ),
                }
            )
            continue

        _assert_matched_feature_rows(
            baseline_train_source,
            train,
            context=f"{window.name} training",
        )
        _assert_matched_feature_rows(
            baseline_validation_source,
            validation,
            context=f"{window.name} validation",
        )
        baseline_train = freeze_v23_feature_contract(baseline_train_source)
        baseline_validation = freeze_v23_feature_contract(baseline_validation_source)

        baseline_model = model_factory()
        baseline_start = perf_counter()
        baseline_model.fit(baseline_train)
        baseline_probability, baseline_components = baseline_model.predict_proba(
            baseline_validation
        )
        baseline_runtime = perf_counter() - baseline_start

        candidate_model = model_factory()
        candidate_start = perf_counter()
        candidate_model.fit(train)
        candidate_probability, candidate_components = candidate_model.predict_proba(validation)
        candidate_runtime = perf_counter() - candidate_start

        result = validation[_prediction_identity_columns(validation)].copy()
        result["window"] = window.name
        result["role"] = window.role
        result["baseline_probability"] = baseline_probability
        result["candidate_probability"] = candidate_probability
        result["baseline_pick_team_a"] = baseline_probability >= 0.5
        result["candidate_pick_team_a"] = candidate_probability >= 0.5
        result["models_disagree"] = (
            result["baseline_pick_team_a"] != result["candidate_pick_team_a"]
        )
        result["baseline_confidence"] = np.maximum(
            baseline_probability, 1 - baseline_probability
        )
        result["candidate_confidence"] = np.maximum(
            candidate_probability, 1 - candidate_probability
        )
        for name, values in baseline_components.items():
            result[f"baseline_component_{name}"] = values
        for name, values in candidate_components.items():
            result[f"candidate_component_{name}"] = values
        predictions.append(result)

        baseline_metrics = probability_metrics(
            validation["a_win"], baseline_probability, bins=calibration_bins
        )
        candidate_metrics = probability_metrics(
            validation["a_win"], candidate_probability, bins=calibration_bins
        )
        row = _fold_metric_row(
            window=window,
            train_n=len(train),
            validation_n=len(validation),
            baseline_metrics=baseline_metrics,
            candidate_metrics=candidate_metrics,
            baseline_runtime_seconds=baseline_runtime,
            candidate_runtime_seconds=candidate_runtime,
        )
        row["status"] = "completed"
        folds.append(row)

    prediction_frame = (
        pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    )
    return prediction_frame, pd.DataFrame(folds)


def run_locked_holdout(
    features: pd.DataFrame,
    window: ValidationWindow,
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
    calibration_bins: int = 10,
    baseline_features: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if window.role != "holdout":
        raise ValueError("run_locked_holdout requires a holdout window")
    return run_matched_walk_forward(
        features,
        [window],
        model_factory=model_factory,
        calibration_bins=calibration_bins,
        baseline_features=baseline_features,
    )


def _confidence_band(probability: pd.Series) -> pd.Series:
    confidence = np.maximum(probability, 1 - probability)
    return pd.cut(
        confidence,
        bins=[0.50, 0.55, 0.60, 0.65, 0.70, 1.001],
        labels=["50-54%", "55-59%", "60-64%", "65-69%", "70%+"],
        include_lowest=True,
        right=False,
    ).astype("string")


def subgroup_metrics(
    predictions: pd.DataFrame,
    *,
    minimum_games: int = 20,
    calibration_bins: int = 5,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    required = {"a_win", "baseline_probability", "candidate_probability"}
    missing = sorted(required.difference(predictions.columns))
    if missing:
        raise ValueError(f"Missing prediction columns: {', '.join(missing)}")

    frame = predictions.copy()
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M").astype(str)
    frame["candidate_confidence_band"] = _confidence_band(frame["candidate_probability"])
    frame["agreement"] = np.where(frame["models_disagree"], "disagree", "agree")
    dimensions: list[tuple[str, pd.Series]] = [
        ("all", pd.Series("all", index=frame.index, dtype="string")),
        ("month", frame["month"].astype("string")),
        ("candidate_confidence", frame["candidate_confidence_band"]),
        ("baseline_candidate", frame["agreement"].astype("string")),
    ]
    if "team_a_is_home" in frame:
        dimensions.append(
            (
                "team_a_location",
                frame["team_a_is_home"].map({1.0: "home", 0.0: "away"}).fillna("unknown"),
            )
        )
    if "missing_home_away" in frame:
        dimensions.append(
            (
                "home_away_status",
                frame["missing_home_away"].map({0.0: "known", 1.0: "missing"}).fillna("unknown"),
            )
        )
    if "lineups_confirmed" in frame:
        dimensions.append(
            (
                "lineup_status",
                frame["lineups_confirmed"].map({True: "confirmed", False: "unconfirmed"}),
            )
        )

    rows: list[dict[str, Any]] = []
    for dimension, values in dimensions:
        for value in values.dropna().unique():
            group = frame[values == value]
            if len(group) < minimum_games and dimension != "all":
                continue
            baseline = probability_metrics(
                group["a_win"], group["baseline_probability"], bins=calibration_bins
            )
            candidate = probability_metrics(
                group["a_win"], group["candidate_probability"], bins=calibration_bins
            )
            rows.append(
                {
                    "dimension": dimension,
                    "value": str(value),
                    "n": len(group),
                    **{f"baseline_{key}": metric for key, metric in baseline.items()},
                    **{f"candidate_{key}": metric for key, metric in candidate.items()},
                    "accuracy_difference": candidate["accuracy"] - baseline["accuracy"],
                    "brier_difference": candidate["brier"] - baseline["brier"],
                    "log_loss_difference": candidate["log_loss"] - baseline["log_loss"],
                    "auc_difference": candidate["auc"] - baseline["auc"],
                    "ece_difference": candidate["ece"] - baseline["ece"],
                }
            )
    return pd.DataFrame(rows)


def load_merge_gates(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def evaluate_promotion_gates(
    *,
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    gate_config: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requirements = gate_config.get("requirements", {})
    evidence = dict(evidence or {})
    rows: list[dict[str, Any]] = []

    def add(name: str, status: str, observed: Any, required: Any, detail: str) -> None:
        rows.append(
            {
                "gate": name,
                "status": status,
                "observed": observed,
                "required": required,
                "detail": detail,
            }
        )

    minimum_games = int(requirements.get("minimum_walk_forward_games", 0))
    observed_games = int(candidate_metrics.get("n", 0))
    add(
        "minimum_walk_forward_games",
        "PASS" if observed_games >= minimum_games else "FAIL",
        observed_games,
        minimum_games,
        "Candidate and baseline are evaluated on matched chronological games.",
    )

    if requirements.get("brier_improvement_required", False):
        difference = float(candidate_metrics["brier"] - baseline_metrics["brier"])
        add(
            "brier_improvement",
            "PASS" if difference < 0 else "FAIL",
            difference,
            "candidate minus baseline < 0",
            "Lower Brier score is better.",
        )
    if requirements.get("log_loss_improvement_required", False):
        difference = float(candidate_metrics["log_loss"] - baseline_metrics["log_loss"])
        add(
            "log_loss_improvement",
            "PASS" if difference < 0 else "FAIL",
            difference,
            "candidate minus baseline < 0",
            "Lower log loss is better.",
        )

    auc_tolerance = float(requirements.get("auc_not_worse_by_more_than", 0.0))
    auc_difference = float(candidate_metrics["auc"] - baseline_metrics["auc"])
    add(
        "auc_regression_limit",
        "PASS" if auc_difference >= -auc_tolerance else "FAIL",
        auc_difference,
        f">= {-auc_tolerance}",
        "Positive AUC difference favors the candidate.",
    )

    accuracy_tolerance = float(requirements.get("accuracy_not_worse_by_more_than", 0.0))
    accuracy_difference = float(candidate_metrics["accuracy"] - baseline_metrics["accuracy"])
    add(
        "accuracy_regression_limit",
        "PASS" if accuracy_difference >= -accuracy_tolerance else "FAIL",
        accuracy_difference,
        f">= {-accuracy_tolerance}",
        "Positive accuracy difference favors the candidate.",
    )

    ece_tolerance = float(requirements.get("ece_not_worse_by_more_than", 0.0))
    ece_difference = float(candidate_metrics["ece"] - baseline_metrics["ece"])
    add(
        "calibration_regression_limit",
        "PASS" if ece_difference <= ece_tolerance else "FAIL",
        ece_difference,
        f"<= {ece_tolerance}",
        "Lower expected calibration error is better.",
    )

    coverage_tolerance = float(requirements.get("coverage_not_worse_by_more_than", 0.0))
    coverage_difference = float(candidate_metrics["coverage"] - baseline_metrics["coverage"])
    add(
        "coverage_regression_limit",
        "PASS" if coverage_difference >= -coverage_tolerance else "FAIL",
        coverage_difference,
        f">= {-coverage_tolerance}",
        "Candidate coverage must not materially decline.",
    )

    evidence_requirements = {
        "minimum_prospective_games": "prospective_games",
        "closing_line_value_tracking_required": "closing_line_value_tracking",
        "no_schedule_integrity_errors": "schedule_integrity_passed",
        "no_target_leakage": "target_leakage_tests_passed",
        "point_in_time_provenance_required": "point_in_time_provenance",
        "final_holdout_required": "final_holdout_passed",
    }
    for requirement_name, evidence_name in evidence_requirements.items():
        requirement = requirements.get(requirement_name)
        if requirement in (None, False, 0):
            continue
        observed = evidence.get(evidence_name)
        if requirement_name == "minimum_prospective_games":
            if observed is None:
                status = "PENDING"
            else:
                status = "PASS" if int(observed) >= int(requirement) else "FAIL"
        else:
            status = "PENDING" if observed is None else ("PASS" if bool(observed) else "FAIL")
        add(requirement_name, status, observed, requirement, "Release evidence gate.")

    statuses = {row["status"] for row in rows}
    overall = "FAIL" if "FAIL" in statuses else ("PENDING" if "PENDING" in statuses else "PASS")
    return {
        "overall_status": overall,
        "production_branch": gate_config.get("production_branch"),
        "candidate_branch": gate_config.get("candidate_branch"),
        "gates": rows,
        "policy": gate_config.get("policy", ""),
    }


def dataframe_fingerprint(paths: Iterable[str | Path]) -> str:
    digest = sha256()
    for path in sorted((Path(path) for path in paths), key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()
