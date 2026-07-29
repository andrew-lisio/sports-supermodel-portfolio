from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .evidence import ProspectiveEvidenceLedger


CONFLICT_AUDIT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ConflictAuditConfig:
    """Configuration for evaluating the abstention filter prospectively.

    The filter is a recommendation gate, not a second prediction model. The raw
    prediction is always graded. A filtered game is considered a helpful pass only
    when the raw prediction loses.
    """

    track: str = "shadow"
    minimum_graded_games: int = 100
    minimum_filtered_games: int = 40

    def __post_init__(self) -> None:
        if self.track not in {"production", "shadow"}:
            raise ValueError("track must be 'production' or 'shadow'")
        if self.minimum_graded_games <= 0:
            raise ValueError("minimum_graded_games must be positive")
        if self.minimum_filtered_games <= 0:
            raise ValueError("minimum_filtered_games must be positive")


def _latest_events_by_game(events: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    by_game: dict[int, dict[str, Any]] = {}
    for event in events:
        game_pk = int(event["game_pk"])
        bucket = by_game.setdefault(game_pk, {})
        bucket[str(event["event_type"])] = dict(event)
    return by_game


def _pick_from_home_probability(away: str, home: str, home_probability: float) -> str:
    return home if float(home_probability) >= 0.5 else away


def _prediction_fields(payload: Mapping[str, Any], track: str) -> dict[str, Any]:
    away = str(payload["away_team"])
    home = str(payload["home_team"])
    if track == "production":
        home_probability = float(payload["production_home_probability"])
        away_probability = float(payload["production_away_probability"])
        pick = str(
            payload.get("production_raw_pick")
            or _pick_from_home_probability(away, home, home_probability)
        )
        status = str(payload.get("production_selection_status") or "UNKNOWN")
        reasons = str(payload.get("production_selection_reasons") or "")
        overlap = payload.get("production_model_overlap")
    else:
        home_probability = float(payload["home_probability"])
        away_probability = float(payload["away_probability"])
        pick = str(
            payload.get("shadow_raw_pick")
            or payload.get("raw_pick")
            or _pick_from_home_probability(away, home, home_probability)
        )
        status = str(
            payload.get("shadow_selection_status")
            or payload.get("selection_status")
            or "UNKNOWN"
        )
        reasons = str(
            payload.get("shadow_selection_reasons")
            or payload.get("selection_reasons")
            or ""
        )
        overlap = payload.get("model_overlap")
    return {
        "away_team": away,
        "home_team": home,
        "raw_pick": pick,
        "home_probability": home_probability,
        "away_probability": away_probability,
        "pick_probability": max(home_probability, away_probability),
        "selection_status": status,
        "selection_reasons": reasons,
        "model_overlap": int(overlap) if overlap is not None else None,
        "selection_policy_version": payload.get("selection_policy_version"),
        "selection_policy_mode": payload.get("selection_policy_mode"),
    }


def _reason_summary(rows: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    reason_values: set[str] = set()
    for value in rows["selection_reasons"].fillna("").astype(str):
        reason_values.update(item for item in value.split(";") if item)
    for reason in sorted(reason_values):
        mask = rows["selection_reasons"].fillna("").astype(str).str.split(";").apply(
            lambda parts: reason in parts
        )
        subset = rows.loc[mask]
        raw_wins = int(subset["raw_correct"].sum())
        games = int(len(subset))
        raw_losses = games - raw_wins
        records.append(
            {
                "reason": reason,
                "games": games,
                "raw_wins": raw_wins,
                "raw_losses": raw_losses,
                "helpful_pass_rate": (raw_losses / games) if games else None,
            }
        )
    return records


def audit_conflict_filter(
    ledger_path: str | Path,
    *,
    config: ConflictAuditConfig | None = None,
) -> dict[str, Any]:
    """Grade raw predictions and the filter's abstentions from the evidence ledger."""

    config = config or ConflictAuditConfig()
    ledger = ProspectiveEvidenceLedger(ledger_path)
    events = ledger.read(verify=True)
    by_game = _latest_events_by_game(events)
    rows: list[dict[str, Any]] = []

    for game_pk, game_events in sorted(by_game.items()):
        prediction = game_events.get("prediction")
        outcome = game_events.get("outcome")
        if prediction is None or outcome is None:
            continue
        prediction_payload = prediction.get("payload") or {}
        outcome_payload = outcome.get("payload") or {}
        fields = _prediction_fields(prediction_payload, config.track)
        home_won = bool(int(outcome_payload["home_won"]))
        actual_winner = fields["home_team"] if home_won else fields["away_team"]
        raw_correct = fields["raw_pick"] == actual_winner
        filtered = fields["selection_status"].upper() == "PASS"
        rows.append(
            {
                "game_pk": game_pk,
                "game_date": prediction_payload.get("game_date"),
                **fields,
                "actual_winner": actual_winner,
                "raw_correct": raw_correct,
                "filtered": filtered,
                "helpful_pass": filtered and not raw_correct,
                "false_pass": filtered and raw_correct,
                "scheduled_start": prediction.get("scheduled_start"),
                "prediction_recorded_at": prediction.get("recorded_at"),
                "outcome_recorded_at": outcome.get("recorded_at"),
            }
        )

    frame = pd.DataFrame(rows)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if frame.empty:
        return {
            "schema_version": CONFLICT_AUDIT_SCHEMA_VERSION,
            "generated_at_utc": generated_at,
            "ledger": str(Path(ledger_path)),
            "track": config.track,
            "evidence_status": "PENDING",
            "summary": {
                "graded_games": 0,
                "filtered_games": 0,
                "eligible_games": 0,
                "raw_accuracy": None,
                "eligible_accuracy": None,
                "filtered_raw_accuracy": None,
                "helpful_pass_rate": None,
                "coverage": None,
            },
            "requirements": {
                "minimum_graded_games": config.minimum_graded_games,
                "minimum_filtered_games": config.minimum_filtered_games,
            },
            "reason_summary": [],
            "games": [],
        }

    policy_evaluable = frame.loc[
        frame["selection_status"].astype(str).str.upper().isin({"PASS", "ELIGIBLE"})
    ]
    filtered = policy_evaluable.loc[policy_evaluable["filtered"]]
    eligible = policy_evaluable.loc[~policy_evaluable["filtered"]]
    graded_games = int(len(frame))
    policy_evaluable_games = int(len(policy_evaluable))
    unclassifiable_games = graded_games - policy_evaluable_games
    filtered_games = int(len(filtered))
    eligible_games = int(len(eligible))
    raw_wins = int(frame["raw_correct"].sum())
    eligible_wins = int(eligible["raw_correct"].sum())
    filtered_raw_wins = int(filtered["raw_correct"].sum())
    helpful_passes = int(filtered["helpful_pass"].sum())
    false_passes = int(filtered["false_pass"].sum())
    ready = (
        policy_evaluable_games >= config.minimum_graded_games
        and filtered_games >= config.minimum_filtered_games
    )

    game_columns = [
        "game_pk",
        "game_date",
        "away_team",
        "home_team",
        "raw_pick",
        "actual_winner",
        "raw_correct",
        "pick_probability",
        "model_overlap",
        "selection_status",
        "selection_reasons",
        "filtered",
        "helpful_pass",
        "false_pass",
        "selection_policy_version",
        "selection_policy_mode",
    ]
    game_records = frame[game_columns].sort_values(
        ["game_date", "game_pk"], na_position="last"
    ).to_dict("records")

    return {
        "schema_version": CONFLICT_AUDIT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "ledger": str(Path(ledger_path)),
        "track": config.track,
        "evidence_status": "READY_FOR_REVIEW" if ready else "PENDING",
        "summary": {
            "graded_games": graded_games,
            "policy_evaluable_games": policy_evaluable_games,
            "unclassifiable_games": unclassifiable_games,
            "filtered_games": filtered_games,
            "eligible_games": eligible_games,
            "raw_wins": raw_wins,
            "raw_losses": graded_games - raw_wins,
            "raw_accuracy": raw_wins / graded_games,
            "eligible_wins": eligible_wins,
            "eligible_losses": eligible_games - eligible_wins,
            "eligible_accuracy": (eligible_wins / eligible_games) if eligible_games else None,
            "filtered_raw_wins": filtered_raw_wins,
            "filtered_raw_losses": filtered_games - filtered_raw_wins,
            "filtered_raw_accuracy": (
                filtered_raw_wins / filtered_games if filtered_games else None
            ),
            "helpful_passes": helpful_passes,
            "false_passes": false_passes,
            "helpful_pass_rate": helpful_passes / filtered_games if filtered_games else None,
            "coverage": (
                eligible_games / policy_evaluable_games if policy_evaluable_games else None
            ),
            "overall_recommendation_coverage": eligible_games / graded_games,
            "accuracy_lift_eligible_vs_raw": (
                (eligible_wins / eligible_games) - (raw_wins / graded_games)
                if eligible_games
                else None
            ),
        },
        "requirements": {
            "minimum_graded_games": config.minimum_graded_games,
            "minimum_filtered_games": config.minimum_filtered_games,
            "graded_games_remaining": max(
                0, config.minimum_graded_games - policy_evaluable_games
            ),
            "filtered_games_remaining": max(0, config.minimum_filtered_games - filtered_games),
        },
        "interpretation": (
            "The conflict filter is an abstention/recommendation gate. It is not credited "
            "with predicting the opponent. Helpful passes are filtered games where the raw "
            "prediction lost; false passes are filtered games where the raw prediction won."
        ),
        "reason_summary": _reason_summary(frame),
        "games": game_records,
    }


def write_conflict_audit(
    ledger_path: str | Path,
    output_path: str | Path,
    *,
    config: ConflictAuditConfig | None = None,
) -> dict[str, Any]:
    report = audit_conflict_filter(ledger_path, config=config)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
