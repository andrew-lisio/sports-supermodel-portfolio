from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .mlb_v2 import V2Ensemble, load_team_logs, reconstruct_games
from .recent_form import load_recent_form_experiment_plan, run_recent_form_experiments
from .validation import load_validation_plan


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run leakage-safe V2.4 recent-form ablation and decay experiments."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    parser.add_argument(
        "--validation-plan", type=Path, default=Path("config/validation_plan.yaml")
    )
    parser.add_argument(
        "--experiment-plan",
        type=Path,
        default=Path("config/recent_form_experiments.yaml"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/v2_4_recent_form")
    )
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _report(summary: pd.DataFrame, comparisons: pd.DataFrame, selection: dict[str, Any]) -> str:
    lines = [
        "# V2.4 Recent-Form Optimization",
        "",
        "All candidates were evaluated on the same chronological development games. ",
        "The final holdout remained locked.",
        "",
        f"Selection status: **{selection['status']}**",
        "",
        f"Selected contract: **{selection['selected']}**",
        "",
        "| Candidate | Games | Accuracy | Brier | Log loss | AUC | ECE | Form features |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.sort_values(["log_loss", "brier"]).to_dict("records"):
        lines.append(
            "| {candidate} | {n} | {accuracy:.2%} | {brier:.6f} | "
            "{log_loss:.6f} | {auc:.6f} | {ece:.6f} | {recent_form_feature_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Differences versus V2.3.3",
            "",
            "Negative Brier and log-loss differences favor the candidate. Bootstrap intervals are calculated only for the selected contract to keep the experiment practical and avoid spending most runtime resampling rejected candidates.",
            "",
            "| Candidate | Accuracy diff | Brier diff | Log-loss diff | AUC diff | ECE diff |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in comparisons.to_dict("records"):
        lines.append(
            f"| {row['candidate']} | {row['accuracy_difference']:.6f} | "
            f"{row['brier_difference']:.6f} | {row['log_loss_difference']:.6f} | "
            f"{row['auc_difference']:.6f} | {row['ece_difference']:.6f} |"
        )
    bootstrap = selection.get("selected_bootstrap", {})
    if bootstrap:
        lines.extend(["", "## Selected-contract paired bootstrap", ""])
        for metric in ["accuracy", "brier", "log_loss", "auc"]:
            result = bootstrap[metric]
            lines.append(
                f"- {metric}: {result['point']:.6f} "
                f"(95% CI [{result['ci95'][0]:.6f}, {result['ci95'][1]:.6f}])"
            )
    lines.extend(
        [
            "",
            "Selection is deliberately conservative: a more complex contract must clear the configured minimum Brier and log-loss improvements while staying inside accuracy, AUC, and calibration regression limits.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validation_plan = load_validation_plan(args.validation_plan)
    experiment_plan = load_recent_form_experiment_plan(args.experiment_plan)
    games = reconstruct_games(load_team_logs(args.data_dir))
    summary, comparisons, folds, selection = run_recent_form_experiments(
        games,
        validation_plan,
        experiment_plan,
        model_factory=lambda: V2Ensemble(parallel_jobs=1),
    )
    predictions = selection.pop("predictions")
    summary.to_csv(args.output_dir / "candidate_summary.csv", index=False)
    comparisons.to_csv(args.output_dir / "paired_comparisons.csv", index=False)
    folds.to_csv(args.output_dir / "fold_metrics.csv", index=False)
    predictions.to_csv(args.output_dir / "candidate_predictions.csv", index=False)
    (args.output_dir / "selected_contract.json").write_text(
        json.dumps(_json_safe(selection), indent=2), encoding="utf-8"
    )
    (args.output_dir / "RECENT_FORM_REPORT.md").write_text(
        _report(summary, comparisons, selection), encoding="utf-8"
    )
    print(json.dumps(_json_safe(selection), indent=2))
    return 0


def launch() -> None:
    """Run the optimizer and force a clean exit after native ML libraries finish."""

    import os
    import sys

    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
