from __future__ import annotations

import gc
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import yaml

from .mlb_v2 import RECENT_FORM_WINDOWS, V2Ensemble, build_pregame_features
from .model_contract import V24_CANDIDATE_FEATURE_CONTRACT
from .validation import ValidationPlan, paired_bootstrap_differences, probability_metrics

_ADJUSTED_WINDOW_PATTERN = re.compile(
    r"^opp_adj_(?:win|rf|ra|rd)(\d+)(?:_|$)"
)


@dataclass(frozen=True)
class OpponentAdjustedFormContract:
    name: str
    include_adjusted_form: bool
    windows: tuple[int, ...] = RECENT_FORM_WINDOWS
    include_momentum: bool = True
    description: str = ""
    baseline: bool = False

    def __post_init__(self) -> None:
        unknown = sorted(set(self.windows).difference(RECENT_FORM_WINDOWS))
        if unknown:
            raise ValueError(f"Unsupported opponent-adjusted windows: {unknown}")
        if len(set(self.windows)) != len(self.windows):
            raise ValueError("Opponent-adjusted windows cannot contain duplicates")
        if not self.include_adjusted_form and self.include_momentum:
            raise ValueError(
                "include_momentum cannot be true when adjusted form is disabled"
            )


@dataclass(frozen=True)
class OpponentAdjustedExperimentPlan:
    candidates: tuple[OpponentAdjustedFormContract, ...]
    minimum_log_loss_improvement: float = 0.0
    minimum_brier_improvement: float = 0.0
    maximum_accuracy_regression: float = 0.01
    maximum_auc_regression: float = 0.005
    maximum_ece_regression: float = 0.01
    bootstrap_iterations: int = 500

    @property
    def baseline(self) -> OpponentAdjustedFormContract:
        baselines = [candidate for candidate in self.candidates if candidate.baseline]
        if len(baselines) != 1:
            raise ValueError("Exactly one opponent-adjusted candidate must be baseline")
        return baselines[0]


def load_opponent_adjusted_experiment_plan(
    path: str | Path,
) -> OpponentAdjustedExperimentPlan:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    selection = document.get("selection", {})
    candidates: list[OpponentAdjustedFormContract] = []
    for index, raw in enumerate(document.get("candidates", []), start=1):
        include_adjusted = bool(raw.get("include_adjusted_form", True))
        candidates.append(
            OpponentAdjustedFormContract(
                name=str(raw.get("name", f"candidate_{index}")),
                include_adjusted_form=include_adjusted,
                windows=tuple(
                    int(value)
                    for value in raw.get("windows", RECENT_FORM_WINDOWS)
                ),
                include_momentum=bool(
                    raw.get("include_momentum", include_adjusted)
                ),
                description=str(raw.get("description", "")),
                baseline=bool(raw.get("baseline", False)),
            )
        )
    if not candidates:
        raise ValueError("At least one opponent-adjusted candidate is required")
    plan = OpponentAdjustedExperimentPlan(
        candidates=tuple(candidates),
        minimum_log_loss_improvement=float(
            selection.get("minimum_log_loss_improvement", 0.0)
        ),
        minimum_brier_improvement=float(
            selection.get("minimum_brier_improvement", 0.0)
        ),
        maximum_accuracy_regression=float(
            selection.get("maximum_accuracy_regression", 0.01)
        ),
        maximum_auc_regression=float(
            selection.get("maximum_auc_regression", 0.005)
        ),
        maximum_ece_regression=float(
            selection.get("maximum_ece_regression", 0.01)
        ),
        bootstrap_iterations=int(document.get("bootstrap_iterations", 500)),
    )
    _ = plan.baseline
    if plan.bootstrap_iterations <= 0:
        raise ValueError("bootstrap_iterations must be positive")
    return plan


def is_opponent_adjusted_feature(column: str) -> bool:
    return column.startswith("opp_adj_")


def opponent_adjusted_feature_kind(
    column: str,
) -> tuple[str, int | None] | None:
    if not is_opponent_adjusted_feature(column):
        return None
    if column.startswith("opp_adj_form_"):
        return ("momentum", None)
    match = _ADJUSTED_WINDOW_PATTERN.match(column)
    if match:
        return ("window", int(match.group(1)))
    return ("other", None)


def apply_opponent_adjusted_contract(
    features: pd.DataFrame,
    contract: OpponentAdjustedFormContract,
) -> pd.DataFrame:
    """Return one explicit opponent-adjusted feature contract."""

    if not contract.include_adjusted_form:
        return features.drop(
            columns=[column for column in features if is_opponent_adjusted_feature(column)]
        ).copy()

    allowed_windows = set(contract.windows)
    drop: list[str] = []
    for column in features.columns:
        kind = opponent_adjusted_feature_kind(column)
        if kind is None:
            continue
        family, window = kind
        if family == "momentum" and not contract.include_momentum:
            drop.append(column)
        elif family == "window" and window not in allowed_windows:
            drop.append(column)
    return features.drop(columns=drop).copy()


def opponent_adjusted_feature_count(
    features: pd.DataFrame,
    contract: OpponentAdjustedFormContract,
) -> int:
    contracted = apply_opponent_adjusted_contract(features, contract)
    return sum(is_opponent_adjusted_feature(column) for column in contracted.columns)


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


def _run_walk_forward(
    features: pd.DataFrame,
    contract: OpponentAdjustedFormContract,
    validation_plan: ValidationPlan,
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    contracted = apply_opponent_adjusted_contract(features, contract)
    predictions: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for window in validation_plan.development_windows:
        train = contracted[contracted["date"] < window.start]
        validation = contracted[
            (contracted["date"] >= window.start)
            & (contracted["date"] <= window.end)
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
            validation["a_win"],
            probability,
            bins=validation_plan.calibration_bins,
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
        pd.concat(predictions, ignore_index=True)
        if predictions
        else pd.DataFrame(),
        pd.DataFrame(fold_rows),
    )


def _matched_candidate_arrays(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    keys = [
        column
        for column in ["date", "game_pk", "team_a", "team_b"]
        if column in baseline
    ]
    if not keys:
        raise ValueError("Predictions do not contain match identity columns")
    merged = baseline[keys + ["a_win", "probability"]].merge(
        candidate[keys + ["a_win", "probability"]],
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
    plan: OpponentAdjustedExperimentPlan,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if candidate["log_loss"] > (
        baseline["log_loss"] - plan.minimum_log_loss_improvement
    ):
        reasons.append("log_loss_improvement_below_threshold")
    if candidate["brier"] > (
        baseline["brier"] - plan.minimum_brier_improvement
    ):
        reasons.append("brier_improvement_below_threshold")
    if candidate["accuracy"] < (
        baseline["accuracy"] - plan.maximum_accuracy_regression
    ):
        reasons.append("accuracy_regression")
    if candidate["auc"] < baseline["auc"] - plan.maximum_auc_regression:
        reasons.append("auc_regression")
    if candidate["ece"] > baseline["ece"] + plan.maximum_ece_regression:
        reasons.append("calibration_regression")
    return not reasons, reasons


def select_opponent_adjusted_candidate(
    summary: pd.DataFrame,
    plan: OpponentAdjustedExperimentPlan,
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
                {
                    "candidate": row["candidate"],
                    "eligible": True,
                    "reasons": ["baseline"],
                }
            )
            continue
        is_eligible, reasons = _eligible_candidate(baseline, row, plan)
        decisions.append(
            {
                "candidate": row["candidate"],
                "eligible": is_eligible,
                "reasons": reasons,
            }
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
                int(row["opponent_adjusted_feature_count"]),
            ),
        )
        status = "candidate_selected"
    return {
        "status": status,
        "baseline": baseline_name,
        "selected": selected["candidate"],
        "decisions": decisions,
    }


def run_opponent_adjusted_experiments(
    games: pd.DataFrame,
    validation_plan: ValidationPlan,
    experiment_plan: OpponentAdjustedExperimentPlan,
    *,
    model_factory: Callable[[], Any] = V2Ensemble,
    candidate_workers: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Evaluate adjusted-form candidates against the frozen V2.4 contract."""

    features = build_pregame_features(
        games,
        recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        include_opponent_adjusted_recent_form=True,
    )
    if candidate_workers <= 0:
        raise ValueError("candidate_workers must be positive")
    candidate_workers = min(candidate_workers, len(experiment_plan.candidates))

    def evaluate_contract(
        contract: OpponentAdjustedFormContract,
    ) -> tuple[str, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
        predictions, candidate_folds = _run_walk_forward(
            features,
            contract,
            validation_plan,
            model_factory=model_factory,
        )
        if predictions.empty:
            raise RuntimeError(f"Candidate {contract.name} produced no predictions")
        metrics = probability_metrics(
            predictions["a_win"],
            predictions["probability"],
            bins=validation_plan.calibration_bins,
        )
        row = {
            "candidate": contract.name,
            "description": contract.description,
            "baseline": contract.baseline,
            "include_adjusted_form": contract.include_adjusted_form,
            "windows": ",".join(str(value) for value in contract.windows),
            "include_momentum": contract.include_momentum,
            "opponent_adjusted_feature_count": opponent_adjusted_feature_count(
                features, contract
            ),
            "runtime_seconds": float(candidate_folds["runtime_seconds"].fillna(0).sum()),
            **metrics,
        }
        return contract.name, predictions, candidate_folds, row

    contracts = list(experiment_plan.candidates)
    if candidate_workers == 1:
        evaluated = [evaluate_contract(contract) for contract in contracts]
    else:
        with ThreadPoolExecutor(
            max_workers=candidate_workers,
            thread_name_prefix="supermodel-opponent-candidate",
        ) as executor:
            evaluated = list(executor.map(evaluate_contract, contracts))

    predictions_by_name = {name: predictions for name, predictions, _, _ in evaluated}
    folds = [candidate_folds for _, _, candidate_folds, _ in evaluated]
    rows = [row for _, _, _, row in evaluated]

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
            baseline_predictions,
            candidate_predictions,
        )
        candidate_summary = summary.loc[
            summary["candidate"] == contract.name
        ].iloc[0]
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
                    candidate_summary["log_loss"]
                    - baseline_summary["log_loss"]
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
    selection = select_opponent_adjusted_candidate(summary, experiment_plan)
    selected_predictions = predictions_by_name[selection["selected"]]
    _, selected_y, baseline_probability, candidate_probability = (
        _matched_candidate_arrays(baseline_predictions, selected_predictions)
    )
    selection["selected_bootstrap"] = paired_bootstrap_differences(
        selected_y,
        baseline_probability,
        candidate_probability,
        iterations=experiment_plan.bootstrap_iterations,
        seed=validation_plan.random_seed,
    )
    selection["predictions"] = pd.concat(combined_predictions, ignore_index=True)
    return summary, comparisons, pd.concat(folds, ignore_index=True), selection
