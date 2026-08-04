from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


@dataclass(frozen=True)
class ProbabilityMetrics:
    rows: int
    accuracy: float
    brier: float
    log_loss: float
    auc: float | None
    ece: float

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionThresholds:
    minimum_rows: int = 500
    maximum_brier_delta: float = 0.0
    maximum_log_loss_delta: float = 0.0
    minimum_auc_delta: float = 0.0
    maximum_ece_delta: float = 0.0025
    minimum_probability_change: float = 0.002
    bootstrap_samples: int = 2000
    confidence_level: float = 0.95


@dataclass(frozen=True)
class CandidateEvaluation:
    status: str
    generated_at_utc: str
    baseline: ProbabilityMetrics
    candidate: ProbabilityMetrics
    deltas: dict[str, float | None]
    mean_absolute_probability_change: float
    paired_accuracy_delta_ci: tuple[float, float]
    gates: dict[str, dict[str, Any]]
    eligible_for_shadow: bool
    eligible_for_promotion: bool

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["baseline"] = self.baseline.to_record()
        payload["candidate"] = self.candidate.to_record()
        payload["paired_accuracy_delta_ci"] = list(self.paired_accuracy_delta_ci)
        return payload


def expected_calibration_error(
    outcomes: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 10,
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    ids = np.clip(np.digitize(probabilities, edges, right=True) - 1, 0, bins - 1)
    ece = 0.0
    for index in range(bins):
        mask = ids == index
        if not np.any(mask):
            continue
        ece += float(mask.mean()) * abs(float(probabilities[mask].mean()) - float(outcomes[mask].mean()))
    return float(ece)


def probability_metrics(outcomes: np.ndarray, probabilities: np.ndarray) -> ProbabilityMetrics:
    y = np.asarray(outcomes, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-8, 1 - 1e-8)
    if y.shape != p.shape or y.ndim != 1 or len(y) == 0:
        raise ValueError("outcomes and probabilities must be equal-length non-empty vectors")
    if not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("outcomes must be binary")
    accuracy = float(np.mean((p >= 0.5) == y))
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    auc: float | None
    try:
        auc = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None
    except ValueError:
        auc = None
    return ProbabilityMetrics(
        rows=len(y),
        accuracy=accuracy,
        brier=brier,
        log_loss=log_loss,
        auc=auc,
        ece=expected_calibration_error(y, p),
    )


def paired_accuracy_bootstrap_ci(
    outcomes: np.ndarray,
    baseline: np.ndarray,
    candidate: np.ndarray,
    *,
    samples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 20260804,
) -> tuple[float, float]:
    y = np.asarray(outcomes, dtype=float)
    baseline_correct = (np.asarray(baseline) >= 0.5) == y
    candidate_correct = (np.asarray(candidate) >= 0.5) == y
    rng = np.random.default_rng(seed)
    deltas = np.empty(samples, dtype=float)
    for index in range(samples):
        selected = rng.integers(0, len(y), len(y))
        deltas[index] = float(
            candidate_correct[selected].mean() - baseline_correct[selected].mean()
        )
    alpha = 1.0 - confidence_level
    return (
        float(np.quantile(deltas, alpha / 2.0)),
        float(np.quantile(deltas, 1.0 - alpha / 2.0)),
    )


def _gate(passed: bool, observed: Any, requirement: str) -> dict[str, Any]:
    return {"status": "PASS" if passed else "FAIL", "observed": observed, "requirement": requirement}


def evaluate_candidate_probabilities(
    frame: pd.DataFrame,
    *,
    outcome_column: str = "outcome",
    baseline_column: str = "baseline_probability",
    candidate_column: str = "candidate_probability",
    thresholds: PromotionThresholds | None = None,
) -> CandidateEvaluation:
    active = thresholds or PromotionThresholds()
    clean = frame[[outcome_column, baseline_column, candidate_column]].dropna()
    y = clean[outcome_column].astype(float).to_numpy()
    baseline_p = clean[baseline_column].astype(float).to_numpy()
    candidate_p = clean[candidate_column].astype(float).to_numpy()
    baseline = probability_metrics(y, baseline_p)
    candidate = probability_metrics(y, candidate_p)
    deltas: dict[str, float | None] = {
        "accuracy": candidate.accuracy - baseline.accuracy,
        "brier": candidate.brier - baseline.brier,
        "log_loss": candidate.log_loss - baseline.log_loss,
        "auc": (
            candidate.auc - baseline.auc
            if candidate.auc is not None and baseline.auc is not None
            else None
        ),
        "ece": candidate.ece - baseline.ece,
    }
    probability_change = float(np.mean(np.abs(candidate_p - baseline_p)))
    ci = paired_accuracy_bootstrap_ci(
        y,
        baseline_p,
        candidate_p,
        samples=active.bootstrap_samples,
        confidence_level=active.confidence_level,
    )
    gates = {
        "sample_size": _gate(len(clean) >= active.minimum_rows, len(clean), f">={active.minimum_rows}"),
        "probability_change": _gate(
            probability_change >= active.minimum_probability_change,
            probability_change,
            f">={active.minimum_probability_change}",
        ),
        "brier": _gate(
            float(deltas["brier"]) <= active.maximum_brier_delta,
            deltas["brier"],
            f"<={active.maximum_brier_delta}",
        ),
        "log_loss": _gate(
            float(deltas["log_loss"]) <= active.maximum_log_loss_delta,
            deltas["log_loss"],
            f"<={active.maximum_log_loss_delta}",
        ),
        "auc": _gate(
            deltas["auc"] is not None and float(deltas["auc"]) >= active.minimum_auc_delta,
            deltas["auc"],
            f">={active.minimum_auc_delta}",
        ),
        "ece": _gate(
            float(deltas["ece"]) <= active.maximum_ece_delta,
            deltas["ece"],
            f"<={active.maximum_ece_delta}",
        ),
    }
    retrospective_pass = all(item["status"] == "PASS" for item in gates.values())
    # A retrospective result can qualify a candidate for prospective shadowing, but
    # never for production promotion by itself.
    eligible_for_shadow = retrospective_pass
    eligible_for_promotion = False
    return CandidateEvaluation(
        status="RETROSPECTIVE_PASS" if retrospective_pass else "NOT_ELIGIBLE",
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        baseline=baseline,
        candidate=candidate,
        deltas=deltas,
        mean_absolute_probability_change=probability_change,
        paired_accuracy_delta_ci=ci,
        gates=gates,
        eligible_for_shadow=eligible_for_shadow,
        eligible_for_promotion=eligible_for_promotion,
    )


def chronological_folds(
    frame: pd.DataFrame,
    *,
    date_column: str = "date",
    minimum_train_rows: int = 300,
    fold_size: int = 100,
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    ordered = frame.assign(_date=pd.to_datetime(frame[date_column])).sort_values("_date").reset_index(drop=True)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    start = minimum_train_rows
    while start < len(ordered):
        end = min(len(ordered), start + fold_size)
        folds.append((np.arange(0, start), np.arange(start, end)))
        start = end
    return tuple(folds)


def write_candidate_report(report: CandidateEvaluation, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report.to_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
