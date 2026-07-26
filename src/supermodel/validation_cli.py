from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from . import __version__
from .mlb_v2 import build_pregame_features, load_team_logs, reconstruct_games
from .model_contract import V23_FEATURE_CONTRACT, V24_CANDIDATE_FEATURE_CONTRACT
from .validation import (
    calibration_table,
    dataframe_fingerprint,
    evaluate_promotion_gates,
    load_merge_gates,
    load_validation_plan,
    paired_bootstrap_differences,
    probability_metrics,
    run_locked_holdout,
    run_matched_walk_forward,
    subgroup_metrics,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the matched chronological V2.3.3 versus V2.4 validation and "
            "write reproducible reports."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument(
        "--plan", type=Path, default=Path("config/validation_plan.yaml")
    )
    parser.add_argument(
        "--merge-gates", type=Path, default=Path("config/merge_gates.yaml")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/v2_4_validation")
    )
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=None,
        help="Override the bootstrap count in the validation plan.",
    )
    parser.add_argument(
        "--unlock-holdout",
        action="store_true",
        help=(
            "Explicitly evaluate the reserved final holdout. Do not use this during "
            "feature selection or tuning."
        ),
    )
    return parser.parse_args(argv)


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2, allow_nan=True), encoding="utf-8")


def _format_metric(value: Any, *, percentage: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if pd.isna(number):
        return "n/a"
    return f"{number:.2%}" if percentage else f"{number:.6f}"


def _markdown_report(
    *,
    summary: dict[str, Any],
    gate_report: dict[str, Any],
    holdout_summary: dict[str, Any] | None,
) -> str:
    baseline = summary["baseline"]
    candidate = summary["candidate"]
    lines = [
        "# V2.4 Matched Chronological Validation",
        "",
        "V2.3.3 and V2.4 were trained and evaluated on identical chronological games. ",
        "The baseline removes only the Phase 3 feature additions, recreating the frozen ",
        "V2.3.3 predictive feature contract while preserving all game cutoffs.",
        "",
        "## Development walk-forward metrics",
        "",
        "| Version | Games | Accuracy | Brier | Log loss | AUC | ECE | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| V2.3.3 baseline | {baseline['n']} | "
            f"{_format_metric(baseline['accuracy'], percentage=True)} | "
            f"{_format_metric(baseline['brier'])} | "
            f"{_format_metric(baseline['log_loss'])} | "
            f"{_format_metric(baseline['auc'])} | "
            f"{_format_metric(baseline['ece'])} | "
            f"{_format_metric(baseline['coverage'], percentage=True)} |"
        ),
        (
            f"| V2.4 candidate | {candidate['n']} | "
            f"{_format_metric(candidate['accuracy'], percentage=True)} | "
            f"{_format_metric(candidate['brier'])} | "
            f"{_format_metric(candidate['log_loss'])} | "
            f"{_format_metric(candidate['auc'])} | "
            f"{_format_metric(candidate['ece'])} | "
            f"{_format_metric(candidate['coverage'], percentage=True)} |"
        ),
        "",
        "Lower Brier score, log loss, and ECE are better. Higher accuracy and AUC are better.",
        "",
        "## Promotion gates",
        "",
        f"Overall status: **{gate_report['overall_status']}**",
        "",
        "| Gate | Status | Observed | Required |",
        "|---|---|---:|---|",
    ]
    for gate in gate_report["gates"]:
        lines.append(
            f"| {gate['gate']} | {gate['status']} | {gate['observed']} | {gate['required']} |"
        )
    lines.extend(
        [
            "",
            "A pending gate is not a pass. V2.4 must remain off `main` until all release ",
            "evidence gates, including the locked holdout and prospective ledger, are complete.",
            "",
            "## Holdout",
            "",
        ]
    )
    if holdout_summary is None:
        lines.append(
            "The final holdout remained locked. This is the expected state during feature development."
        )
    elif holdout_summary.get("status") == "unavailable":
        lines.append("The holdout was unlocked, but no completed games were available in its date range.")
    else:
        lines.append(
            f"The holdout was evaluated on {holdout_summary['candidate']['n']} matched games."
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Package version: `{summary['metadata']['package_version']}`",
            f"- Git commit: `{summary['metadata']['git_commit']}`",
            f"- Data fingerprint: `{summary['metadata']['data_fingerprint']}`",
            f"- Generated at: `{summary['metadata']['generated_at_utc']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _summary_for_predictions(
    predictions: pd.DataFrame,
    *,
    bins: int,
) -> dict[str, Any]:
    return {
        "baseline": probability_metrics(
            predictions["a_win"], predictions["baseline_probability"], bins=bins
        ),
        "candidate": probability_metrics(
            predictions["a_win"], predictions["candidate_probability"], bins=bins
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = perf_counter()
    plan = load_validation_plan(args.plan)
    bootstrap_iterations = (
        args.bootstrap_iterations
        if args.bootstrap_iterations is not None
        else plan.bootstrap_iterations
    )
    if bootstrap_iterations <= 0:
        raise ValueError("bootstrap iterations must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    data_files = sorted(args.data_dir.glob("*.csv"))
    if not data_files:
        raise FileNotFoundError(f"No team CSV files found under {args.data_dir}")

    logs = load_team_logs(args.data_dir)
    games = reconstruct_games(logs)
    baseline_features = build_pregame_features(
        games, recent_form_alpha=V23_FEATURE_CONTRACT.recent_form_alpha
    )
    candidate_features = build_pregame_features(
        games, recent_form_alpha=V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha
    )

    predictions, folds = run_matched_walk_forward(
        candidate_features,
        plan.development_windows,
        calibration_bins=plan.calibration_bins,
        baseline_features=baseline_features,
    )
    if predictions.empty:
        raise RuntimeError("No development predictions were produced")

    metric_summary = _summary_for_predictions(predictions, bins=plan.calibration_bins)
    bootstrap = paired_bootstrap_differences(
        predictions["a_win"],
        predictions["baseline_probability"],
        predictions["candidate_probability"],
        iterations=bootstrap_iterations,
        seed=plan.random_seed,
    )

    baseline_calibration = calibration_table(
        predictions["a_win"], predictions["baseline_probability"], bins=plan.calibration_bins
    ).assign(version="v2.3.3")
    candidate_calibration = calibration_table(
        predictions["a_win"], predictions["candidate_probability"], bins=plan.calibration_bins
    ).assign(version="v2.4")
    calibration = pd.concat(
        [baseline_calibration, candidate_calibration], ignore_index=True
    )
    subgroups = subgroup_metrics(predictions)

    holdout_predictions = pd.DataFrame()
    holdout_folds = pd.DataFrame()
    holdout_summary: dict[str, Any] | None = None
    if args.unlock_holdout:
        if plan.holdout_window is None:
            raise ValueError("Validation plan has no holdout window")
        holdout_predictions, holdout_folds = run_locked_holdout(
            candidate_features,
            plan.holdout_window,
            calibration_bins=plan.calibration_bins,
            baseline_features=baseline_features,
        )
        if holdout_predictions.empty:
            holdout_summary = {"status": "unavailable"}
        else:
            holdout_summary = {
                "status": "evaluated",
                **_summary_for_predictions(
                    holdout_predictions, bins=plan.calibration_bins
                ),
            }

    gate_config = load_merge_gates(args.merge_gates)
    gate_report = evaluate_promotion_gates(
        baseline_metrics=metric_summary["baseline"],
        candidate_metrics=metric_summary["candidate"],
        gate_config=gate_config,
        evidence={
            "final_holdout_passed": (
                None
                if holdout_summary is None or holdout_summary.get("status") != "evaluated"
                else (
                    holdout_summary["candidate"]["brier"]
                    < holdout_summary["baseline"]["brier"]
                    and holdout_summary["candidate"]["log_loss"]
                    < holdout_summary["baseline"]["log_loss"]
                )
            )
        },
    )

    metadata = {
        "package_version": __version__,
        "git_commit": _git_commit(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_directory": str(args.data_dir),
        "data_file_count": len(data_files),
        "data_fingerprint": dataframe_fingerprint(data_files),
        "feature_rows": len(candidate_features),
        "feature_date_min": pd.Timestamp(candidate_features["date"].min()).date().isoformat(),
        "feature_date_max": pd.Timestamp(candidate_features["date"].max()).date().isoformat(),
        "baseline_feature_contract": V23_FEATURE_CONTRACT.name,
        "baseline_recent_form_alpha": V23_FEATURE_CONTRACT.recent_form_alpha,
        "candidate_feature_contract": V24_CANDIDATE_FEATURE_CONTRACT.name,
        "candidate_recent_form_alpha": V24_CANDIDATE_FEATURE_CONTRACT.recent_form_alpha,
        "validation_plan": str(args.plan),
        "merge_gates": str(args.merge_gates),
        "bootstrap_iterations": bootstrap_iterations,
        "holdout_unlocked": bool(args.unlock_holdout),
        "runtime_seconds": perf_counter() - started,
    }
    summary = {
        **metric_summary,
        "differences_candidate_minus_baseline": {
            key: metric_summary["candidate"][key] - metric_summary["baseline"][key]
            for key in ["accuracy", "brier", "log_loss", "auc", "ece", "coverage"]
        },
        "bootstrap": bootstrap,
        "metadata": metadata,
    }

    predictions.to_csv(args.output_dir / "walk_forward_predictions.csv", index=False)
    folds.to_csv(args.output_dir / "walk_forward_folds.csv", index=False)
    calibration.to_csv(args.output_dir / "calibration.csv", index=False)
    subgroups.to_csv(args.output_dir / "subgroup_metrics.csv", index=False)
    _write_json(args.output_dir / "summary.json", summary)
    _write_json(args.output_dir / "promotion_gates.json", gate_report)
    if args.unlock_holdout:
        holdout_predictions.to_csv(args.output_dir / "holdout_predictions.csv", index=False)
        holdout_folds.to_csv(args.output_dir / "holdout_folds.csv", index=False)
        _write_json(args.output_dir / "holdout_summary.json", holdout_summary)
    (args.output_dir / "VALIDATION_REPORT.md").write_text(
        _markdown_report(
            summary=summary,
            gate_report=gate_report,
            holdout_summary=holdout_summary,
        ),
        encoding="utf-8",
    )

    print(json.dumps(_json_safe({"summary": summary, "gates": gate_report}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
