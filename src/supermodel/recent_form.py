from __future__ import annotations

import gc
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import yaml

from .feature_registry import feature_group_for
from .mlb_v2 import DEFAULT_EWM_ALPHA, RECENT_FORM_WINDOWS, V2Ensemble, build_pregame_features
from .validation import ValidationPlan, paired_bootstrap_differences, probability_metrics

_WINDOW_PATTERN = re.compile(r"^(?:win|rf|ra|rd)(\d+)(?:_|$)")


@dataclass(frozen=True)
class RecentFormContract:
    name: str
    windows: tuple[int, ...] = RECENT_FORM_WINDOWS
    include_momentum: bool = True
    include_ewm: bool = True
    include_last_game: bool = True
    ewm_alpha: float = DEFAULT_EWM_ALPHA
    description: str = ""
    baseline: bool = False

    def __post_init__(self) -> None:
        unknown = sorted(set(self.windows).difference(RECENT_FORM_WINDOWS))
        if unknown:
            raise ValueError(f"Unsupported recent-form windows: {unknown}")
        if len(set(self.windows)) != len(self.windows):
            raise ValueError("Recent-form windows cannot contain duplicates")
        if not 0.0 < self.ewm_alpha <= 1.0:
            raise ValueError("ewm_alpha must be in (0, 1]")


@dataclass(frozen=True)
class RecentFormExperimentPlan:
    candidates: tuple[RecentFormContract, ...]
    minimum_log_loss_improvement: float = 0.0
    minimum_brier_improvement: float = 0.0
    maximum_accuracy_regression: float = 0.01
    maximum_auc_regression: float = 0.005
    maximum_ece_regression: float = 0.01
    bootstrap_iterations: int = 500

    @property
    def baseline(self) -> RecentFormContract:
        baselines = [candidate for candidate in self.candidates if candidate.baseline]
        if len(baselines) != 1:
            raise ValueError("Exactly one recent-form candidate must be marked baseline")
        return baselines[0]


def load_recent_form_experiment_plan(path: str | Path) -> RecentFormExperimentPlan:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    selection = document.get("selection", {})
    candidates: list[RecentFormContract] = []
    for index, raw in enumerate(document.get("candidates", []), start=1):
        candidates.append(
            RecentFormContract(
                name=str(raw.get("name", f"candidate_{index}")),
                windows=tuple(int(value) for value in raw.get("windows", RECENT_FORM_WINDOWS)),
                include_momentum=bool(raw.get("include_momentum", True)),
                include_ewm=bool(raw.get("include_ewm", True)),
                include_last_game=bool(raw.get("include_last_game", True)),
                ewm_alpha=float(raw.get("ewm_alpha", DEFAULT_EWM_ALPHA)),
                description=str(raw.get("description", "")),
                baseline=bool(raw.get("baseline", False)),
            )
        )
    if not candidates:
        raise ValueError("At least one recent-form candidate is required")
    plan = RecentFormExperimentPlan(
        candidates=tuple(candidates),
        minimum_log_loss_improvement=float(
            selection.get("minimum_log_loss_improvement", 0.0)
        ),
        minimum_brier_improvement=float(selection.get("minimum_brier_improvement", 0.0)),
        maximum_accuracy_regression=float(selection.get("maximum_accuracy_regression", 0.01)),
        maximum_auc_regression=float(selection.get("maximum_auc_regression", 0.005)),
        maximum_ece_regression=float(selection.get("maximum_ece_regression", 0.01)),
        bootstrap_iterations=int(document.get("bootstrap_iterations", 500)),
    )
    _ = plan.baseline
    if plan.bootstrap_iterations <= 0:
        raise ValueError("bootstrap_iterations must be positive")
    return plan


def _is_recent_form_feature(column: str) -> bool:
    try:
        return feature_group_for(column) == "recent_form"
    except ValueError:
        return False


def recent_form_feature_kind(column: str) -> tuple[str, int | None] | None:
    if not _is_recent_form_feature(column):
        return None
    if column.startswith("last_"):
        return ("last_game", None)
    if column.startswith("ewm_"):
        return ("ewm", None)
    if column.startswith("form_"):
        return ("momentum", None)
    match = _WINDOW_PATTERN.match(column)
    if match:
        return ("window", int(match.group(1)))
    return ("other", None)


def apply_recent_form_contract(
    features: pd.DataFrame,
    contract: RecentFormContract,
) -> pd.DataFrame:
    """Return a feature frame restricted to one explicit recent-form contract."""

    drop: list[str] = []
    allowed_windows = set(contract.windows)
    for column in features.columns:
        kind = recent_form_feature_kind(column)
        if kind is None:
            continue
        family, window = kind
        if family == "last_game" and not contract.include_last_game:
            drop.append(column)
        elif family == "ewm" and not contract.include_ewm:
            drop.append(column)
        elif family == "momentum" and not contract.include_momentum:
            drop.append(column)
        elif family == "window" and window not in allowed_windows:
            drop.append(column)
    return features.drop(columns=drop).copy()


def recent_form_feature_count(features: pd.DataFrame, contract: RecentFormContract) -> int:
    contracted = apply_recent_form_contract(features, contract)
    return sum(_is_recent_form_feature(column) for column in contracted.columns)


def _identity_columns(frame: pd.DataFrame) -> list[str]:
    preferred = [
        "date",
        "game_pk",
        "team_a",
        "team_b",
        "a_win",
        "a_runs",
        "b_runs",
        "team_a_is_home",
        "missing_home_away",
    ]
    return [column for column in preferred if column in frame.columns]


def run_contract_walk_forward(
    features: pd.DataFrame,
    contract: RecentFormContract,
    validation_plan: ValidationPlan,
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    contracted = apply_recent_form_contract(features, contract)
    predictions: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for window in validation_plan.development_windows:
        train = contracted[contracted["date"] < window.start]
        validation = contracted[
            (contracted["date"] >= window.start) & (contracted["date"] <= window.end)
        ].copy()
        if len(train) < window.minimum_training_games or validation.empty:
            fold_rows.append(
                {
                    "candidate": contract.name,
                    "window": window.name,
                    "train_n": len(train),
                    "validation_n": len(validation),
                    "status": "skipped",
                }
            )
            continue
        model = model_factory()
        started = perf_counter()
        model.fit(train)
        probability, components = model.predict_proba(validation)
        runtime = perf_counter() - started
        result = validation[_identity_columns(validation)].copy()
        result["candidate"] = contract.name
        result["window"] = window.name
        result["probability"] = probability
        for name, values in components.items():
            result[f"component_{name}"] = values
        predictions.append(result)
        metrics = probability_metrics(
            validation["a_win"], probability, bins=validation_plan.calibration_bins
        )
        fold_rows.append(
            {
                "candidate": contract.name,
                "window": window.name,
                "train_n": len(train),
                "validation_n": len(validation),
                "runtime_seconds": runtime,
                "status": "completed",
                **metrics,
            }
        )
        del model
        gc.collect()
    return (
        pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
        pd.DataFrame(fold_rows),
    )

def _matched_candidate_arrays(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    keys = [column for column in ["date", "game_pk", "team_a", "team_b"] if column in baseline]
    if not keys:
        raise ValueError("Predictions do not contain match identity columns")
    baseline_columns = keys + ["a_win", "probability"]
    candidate_columns = keys + ["a_win", "probability"]
    merged = baseline[baseline_columns].merge(
        candidate[candidate_columns],
        on=keys,
        how="inner",
        suffixes=("_baseline", "_candidate"),
        validate="one_to_one",
    )
    if not merged["a_win_baseline"].equals(merged["a_win_candidate"]):
        raise ValueError("Matched candidate outcomes differ")
    return (
        merged,
        merged["a_win_baseline"].to_numpy(dtype=int),
        merged["probability_baseline"].to_numpy(dtype=float),
        merged["probability_candidate"].to_numpy(dtype=float),
    )


def _eligible_candidate(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    plan: RecentFormExperimentPlan,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if candidate["log_loss"] > baseline["log_loss"] - plan.minimum_log_loss_improvement:
        reasons.append("log_loss_improvement_below_threshold")
    if candidate["brier"] > baseline["brier"] - plan.minimum_brier_improvement:
        reasons.append("brier_improvement_below_threshold")
    if candidate["accuracy"] < baseline["accuracy"] - plan.maximum_accuracy_regression:
        reasons.append("accuracy_regression")
    if candidate["auc"] < baseline["auc"] - plan.maximum_auc_regression:
        reasons.append("auc_regression")
    if candidate["ece"] > baseline["ece"] + plan.maximum_ece_regression:
        reasons.append("calibration_regression")
    return not reasons, reasons


def select_recent_form_candidate(
    summary: pd.DataFrame,
    plan: RecentFormExperimentPlan,
) -> dict[str, Any]:
    if summary.empty:
        raise ValueError("Candidate summary cannot be empty")
    baseline_name = plan.baseline.name
    baseline_rows = summary[summary["candidate"] == baseline_name]
    if len(baseline_rows) != 1:
        raise ValueError("Candidate summary must contain exactly one baseline row")
    baseline = baseline_rows.iloc[0].to_dict()
    eligible: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for row in summary.to_dict("records"):
        if row["candidate"] == baseline_name:
            decisions.append(
                {"candidate": row["candidate"], "eligible": True, "reasons": ["baseline"]}
            )
            continue
        is_eligible, reasons = _eligible_candidate(baseline, row, plan)
        decisions.append(
            {"candidate": row["candidate"], "eligible": is_eligible, "reasons": reasons}
        )
        if is_eligible:
            eligible.append(row)
    if not eligible:
        selected = baseline
        status = "baseline_retained"
    else:
        selected = min(
            eligible,
            key=lambda row: (
                float(row["log_loss"]),
                float(row["brier"]),
                int(row["recent_form_feature_count"]),
            ),
        )
        status = "candidate_selected"
    return {
        "status": status,
        "baseline": baseline_name,
        "selected": selected["candidate"],
        "decisions": decisions,
    }


def run_recent_form_experiments(
    games: pd.DataFrame,
    validation_plan: ValidationPlan,
    experiment_plan: RecentFormExperimentPlan,
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    features_by_alpha: dict[float, pd.DataFrame] = {}
    predictions_by_name: dict[str, pd.DataFrame] = {}
    folds: list[pd.DataFrame] = []
    rows: list[dict[str, Any]] = []

    for contract in experiment_plan.candidates:
        if contract.ewm_alpha not in features_by_alpha:
            features_by_alpha[contract.ewm_alpha] = build_pregame_features(
                games, recent_form_alpha=contract.ewm_alpha
            )
        features = features_by_alpha[contract.ewm_alpha]
        predictions, candidate_folds = run_contract_walk_forward(
            features,
            contract,
            validation_plan,
            model_factory=model_factory,
        )
        if predictions.empty:
            raise RuntimeError(f"Candidate {contract.name} produced no predictions")
        predictions_by_name[contract.name] = predictions
        folds.append(candidate_folds)
        metrics = probability_metrics(
            predictions["a_win"],
            predictions["probability"],
            bins=validation_plan.calibration_bins,
        )
        rows.append(
            {
                "candidate": contract.name,
                "description": contract.description,
                "baseline": contract.baseline,
                "ewm_alpha": contract.ewm_alpha,
                "windows": ",".join(str(value) for value in contract.windows),
                "include_momentum": contract.include_momentum,
                "include_ewm": contract.include_ewm,
                "include_last_game": contract.include_last_game,
                "recent_form_feature_count": recent_form_feature_count(features, contract),
                "runtime_seconds": float(candidate_folds["runtime_seconds"].fillna(0).sum()),
                **metrics,
            }
        )

    summary = pd.DataFrame(rows)
    baseline_predictions = predictions_by_name[experiment_plan.baseline.name]
    baseline_summary = summary.loc[
        summary["candidate"] == experiment_plan.baseline.name
    ].iloc[0]
    comparison_rows: list[dict[str, Any]] = []
    combined_predictions: list[pd.DataFrame] = []
    for contract in experiment_plan.candidates:
        candidate_predictions = predictions_by_name[contract.name]
        merged, _, _, _ = _matched_candidate_arrays(
            baseline_predictions, candidate_predictions
        )
        candidate_summary = summary.loc[summary["candidate"] == contract.name].iloc[0]
        comparison_rows.append(
            {
                "candidate": contract.name,
                "matched_games": len(merged),
                "accuracy_difference": float(
                    candidate_summary["accuracy"] - baseline_summary["accuracy"]
                ),
                "brier_difference": float(
                    candidate_summary["brier"] - baseline_summary["brier"]
                ),
                "log_loss_difference": float(
                    candidate_summary["log_loss"] - baseline_summary["log_loss"]
                ),
                "auc_difference": float(
                    candidate_summary["auc"] - baseline_summary["auc"]
                ),
                "ece_difference": float(
                    candidate_summary["ece"] - baseline_summary["ece"]
                ),
            }
        )
        combined_predictions.append(candidate_predictions.copy())

    comparisons = pd.DataFrame(comparison_rows)
    selection = select_recent_form_candidate(summary, experiment_plan)
    selected_predictions = predictions_by_name[selection["selected"]]
    _, selected_y, selected_baseline_probability, selected_candidate_probability = (
        _matched_candidate_arrays(baseline_predictions, selected_predictions)
    )
    selection["selected_bootstrap"] = paired_bootstrap_differences(
        selected_y,
        selected_baseline_probability,
        selected_candidate_probability,
        iterations=experiment_plan.bootstrap_iterations,
        seed=validation_plan.random_seed,
    )
    all_predictions = pd.concat(combined_predictions, ignore_index=True)
    return summary, comparisons, pd.concat(folds, ignore_index=True), {
        **selection,
        "predictions": all_predictions,
    }
