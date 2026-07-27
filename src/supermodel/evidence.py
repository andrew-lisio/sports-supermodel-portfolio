from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


EVIDENCE_SCHEMA_VERSION = 1
LEDGER_EVENT_TYPES = {"prediction", "closing_line", "outcome"}
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PREDICTION_KEYS = {
    "a_win",
    "away_runs",
    "away_score",
    "away_won",
    "final",
    "final_score",
    "game_result",
    "home_runs",
    "home_score",
    "home_won",
    "outcome",
    "result",
    "winner",
}


class EvidenceIntegrityError(ValueError):
    """Raised when an append-only evidence ledger fails integrity validation."""


@dataclass(frozen=True)
class EvidenceIssue:
    category: str
    game_pk: int | None
    detail: str
    event_sequence: int | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "game_pk": self.game_pk,
            "detail": self.detail,
            "event_sequence": self.event_sequence,
        }


def _parse_utc(value: str | datetime, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return dt.astimezone(timezone.utc)


def _utc_text(value: str | datetime, *, field_name: str) -> str:
    return _parse_utc(value, field_name=field_name).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _event_digest(event_without_hash: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(event_without_hash)).hexdigest()


def _contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_PREDICTION_KEYS:
                return str(key)
            nested = _contains_forbidden_key(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _contains_forbidden_key(item)
            if nested is not None:
                return nested
    return None


def _validate_probability(value: Any, *, field_name: str) -> float:
    probability = float(value)
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        raise ValueError(f"{field_name} must be a finite probability in [0, 1]")
    return probability


def _validate_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    if event_type == "prediction":
        forbidden = _contains_forbidden_key(payload)
        if forbidden is not None:
            raise EvidenceIntegrityError(
                f"Prediction payload contains outcome-like field {forbidden!r}"
            )
        for key in ("away_team", "home_team", "home_probability", "model_version"):
            if payload.get(key) in (None, ""):
                raise ValueError(f"Prediction payload requires {key}")
        home_probability = _validate_probability(
            payload["home_probability"], field_name="home_probability"
        )
        if payload.get("away_probability") is not None:
            away_probability = _validate_probability(
                payload["away_probability"], field_name="away_probability"
            )
            if abs((home_probability + away_probability) - 1.0) > 1e-6:
                raise ValueError("home_probability and away_probability must sum to one")
        if payload.get("offered_home_implied") is not None:
            _validate_probability(
                payload["offered_home_implied"], field_name="offered_home_implied"
            )
    elif event_type == "closing_line":
        if payload.get("closing_home_implied") is None:
            raise ValueError("Closing-line payload requires closing_home_implied")
        _validate_probability(
            payload["closing_home_implied"], field_name="closing_home_implied"
        )
    elif event_type == "outcome":
        if payload.get("home_won") not in (0, 1, False, True):
            raise ValueError("Outcome payload requires binary home_won")


class ProspectiveEvidenceLedger:
    """Hash-chained append-only evidence ledger keyed by official MLB ``gamePk``.

    Prediction and closing-line events must be recorded no later than the scheduled
    start time. Outcomes must be recorded at or after the scheduled start. Each line
    includes a sequence number, the previous event hash, and a content-derived hash.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_event(self) -> dict[str, Any] | None:
        events = self.read(verify=True)
        return events[-1] if events else None

    def append(
        self,
        *,
        event_type: str,
        game_pk: int,
        recorded_at: str | datetime,
        scheduled_start: str | datetime,
        source: str,
        payload: Mapping[str, Any],
        provenance: Mapping[str, str] | None = None,
        snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        if event_type not in LEDGER_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(LEDGER_EVENT_TYPES)}")
        if int(game_pk) <= 0:
            raise ValueError("game_pk must be positive")
        if not str(source).strip():
            raise ValueError("source is required")

        recorded = _parse_utc(recorded_at, field_name="recorded_at")
        scheduled = _parse_utc(scheduled_start, field_name="scheduled_start")
        if event_type in {"prediction", "closing_line"} and recorded > scheduled:
            raise EvidenceIntegrityError(
                f"{event_type} event was recorded after scheduled start"
            )
        if event_type == "outcome" and recorded < scheduled:
            raise EvidenceIntegrityError("Outcome event was recorded before scheduled start")

        normalized_payload = dict(payload)
        _validate_payload(event_type, normalized_payload)
        normalized_provenance = {
            str(key): str(value)
            for key, value in dict(provenance or {}).items()
            if str(key).strip()
        }
        if snapshot_sha256 is not None and not _HASH_PATTERN.fullmatch(snapshot_sha256):
            raise ValueError("snapshot_sha256 must be a lowercase 64-character SHA-256")

        last = self._last_event()
        sequence = int(last["sequence"]) + 1 if last is not None else 1
        previous_hash = str(last["event_sha256"]) if last is not None else None
        event_without_hash: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "sequence": sequence,
            "event_type": event_type,
            "game_pk": int(game_pk),
            "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
            "scheduled_start": scheduled.isoformat().replace("+00:00", "Z"),
            "source": str(source),
            "snapshot_sha256": snapshot_sha256,
            "provenance": normalized_provenance,
            "payload": normalized_payload,
            "previous_event_sha256": previous_hash,
        }
        event = {**event_without_hash, "event_sha256": _event_digest(event_without_hash)}
        body = _canonical_bytes(event)
        with self.path.open("ab") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read(self, *, verify: bool = True) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise EvidenceIntegrityError(
                        f"Invalid JSON at ledger line {line_number}"
                    ) from exc
                events.append(event)
        if verify:
            verify_evidence_events(events)
        return events

    def sha256(self) -> str | None:
        if not self.path.exists():
            return None
        return sha256(self.path.read_bytes()).hexdigest()


def verify_evidence_events(events: Iterable[Mapping[str, Any]]) -> None:
    previous_hash: str | None = None
    expected_sequence = 1
    seen_hashes: set[str] = set()
    for event in events:
        sequence = int(event.get("sequence", -1))
        if sequence != expected_sequence:
            raise EvidenceIntegrityError(
                f"Expected sequence {expected_sequence}, found {sequence}"
            )
        if event.get("previous_event_sha256") != previous_hash:
            raise EvidenceIntegrityError(f"Broken hash chain at sequence {sequence}")
        claimed_hash = str(event.get("event_sha256", ""))
        if claimed_hash in seen_hashes:
            raise EvidenceIntegrityError(f"Duplicate event hash at sequence {sequence}")
        event_without_hash = dict(event)
        event_without_hash.pop("event_sha256", None)
        actual_hash = _event_digest(event_without_hash)
        if claimed_hash != actual_hash:
            raise EvidenceIntegrityError(f"Event hash mismatch at sequence {sequence}")
        if int(event.get("schema_version", -1)) != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceIntegrityError(
                f"Unsupported evidence schema at sequence {sequence}"
            )
        event_type = str(event.get("event_type", ""))
        if event_type not in LEDGER_EVENT_TYPES:
            raise EvidenceIntegrityError(f"Unknown event type at sequence {sequence}")
        _parse_utc(event["recorded_at"], field_name="recorded_at")
        _parse_utc(event["scheduled_start"], field_name="scheduled_start")
        _validate_payload(event_type, event.get("payload") or {})
        seen_hashes.add(claimed_hash)
        previous_hash = claimed_hash
        expected_sequence += 1


def _latest(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    candidates = [event for event in events if event["event_type"] == event_type]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["recorded_at"], item["sequence"]))


def _gate(status: str, observed: Any, detail: str) -> dict[str, Any]:
    return {"status": status, "observed": observed, "detail": detail}


def _all_provenance_values_valid(provenance: Mapping[str, Any]) -> bool:
    if not provenance:
        return False
    invalid = {"", "missing", "none", "neutral", "neutral_placeholder", "unknown"}
    return all(str(value).strip().lower() not in invalid for value in provenance.values())


def audit_prospective_evidence(
    ledger_path: str | Path,
    *,
    minimum_prospective_games: int = 500,
    required_provenance_keys: Iterable[str] = (
        "schedule",
        "live_feed",
        "pitcher_stats",
        "market_input",
    ),
) -> dict[str, Any]:
    """Audit prospective records and emit machine-readable promotion-gate evidence."""

    path = Path(ledger_path)
    ledger = ProspectiveEvidenceLedger(path)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    issues: list[EvidenceIssue] = []
    try:
        events = ledger.read(verify=True)
        ledger_integrity = True
    except (EvidenceIntegrityError, KeyError, TypeError, ValueError) as exc:
        events = []
        ledger_integrity = False
        issues.append(EvidenceIssue("ledger_integrity", None, str(exc)))

    by_game: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        by_game.setdefault(int(event["game_pk"]), []).append(event)

    eligible_games = 0
    graded_games = 0
    games_with_closing_line = 0
    prediction_count = 0
    starter_identity_games = 0
    starter_stats_complete_games = 0
    starter_stats_partial_games = 0
    diagnostics_rows: list[dict[str, Any]] = []
    required_keys = set(required_provenance_keys)

    for game_pk, game_events in sorted(by_game.items()):
        starts = {event["scheduled_start"] for event in game_events}
        if len(starts) != 1:
            issues.append(
                EvidenceIssue(
                    "schedule_integrity",
                    game_pk,
                    "Conflicting scheduled_start values for one gamePk",
                )
            )
        prediction_events = [
            event for event in game_events if event["event_type"] == "prediction"
        ]
        closing_events = [
            event for event in game_events if event["event_type"] == "closing_line"
        ]
        outcome_events = [event for event in game_events if event["event_type"] == "outcome"]
        prediction_count += len(prediction_events)

        for event in prediction_events + closing_events:
            recorded = _parse_utc(event["recorded_at"], field_name="recorded_at")
            scheduled = _parse_utc(
                event["scheduled_start"], field_name="scheduled_start"
            )
            if recorded > scheduled:
                issues.append(
                    EvidenceIssue(
                        "schedule_integrity",
                        game_pk,
                        f"{event['event_type']} recorded after scheduled start",
                        int(event["sequence"]),
                    )
                )
        for event in outcome_events:
            recorded = _parse_utc(event["recorded_at"], field_name="recorded_at")
            scheduled = _parse_utc(
                event["scheduled_start"], field_name="scheduled_start"
            )
            if recorded < scheduled:
                issues.append(
                    EvidenceIssue(
                        "schedule_integrity",
                        game_pk,
                        "Outcome recorded before scheduled start",
                        int(event["sequence"]),
                    )
                )

        team_pairs = {
            (
                event.get("payload", {}).get("away_team"),
                event.get("payload", {}).get("home_team"),
            )
            for event in prediction_events
        }
        if len(team_pairs) > 1:
            issues.append(
                EvidenceIssue(
                    "schedule_integrity",
                    game_pk,
                    "Conflicting team identity across prediction events",
                )
            )

        for event in prediction_events:
            forbidden = _contains_forbidden_key(event.get("payload") or {})
            if forbidden is not None:
                issues.append(
                    EvidenceIssue(
                        "target_leakage",
                        game_pk,
                        f"Prediction contains outcome-like field {forbidden!r}",
                        int(event["sequence"]),
                    )
                )
            snapshot_hash = event.get("snapshot_sha256")
            provenance = event.get("provenance") or {}
            missing_keys = sorted(required_keys - set(provenance))
            if not snapshot_hash or not _HASH_PATTERN.fullmatch(str(snapshot_hash)):
                issues.append(
                    EvidenceIssue(
                        "provenance",
                        game_pk,
                        "Prediction lacks a valid feature snapshot SHA-256",
                        int(event["sequence"]),
                    )
                )
            if missing_keys:
                issues.append(
                    EvidenceIssue(
                        "provenance",
                        game_pk,
                        f"Prediction provenance is missing keys: {', '.join(missing_keys)}",
                        int(event["sequence"]),
                    )
                )
            if not _all_provenance_values_valid(provenance):
                issues.append(
                    EvidenceIssue(
                        "provenance",
                        game_pk,
                        "Prediction provenance contains missing or placeholder values",
                        int(event["sequence"]),
                    )
                )

            prediction_payload = event.get("payload") or {}
            if any(
                key in prediction_payload
                for key in (
                    "away_starter_id",
                    "home_starter_id",
                    "away_starter_snapshot_sha256",
                    "home_starter_snapshot_sha256",
                )
            ):
                for side in ("away", "home"):
                    pitcher_id = prediction_payload.get(f"{side}_starter_id")
                    starter_hash = prediction_payload.get(
                        f"{side}_starter_snapshot_sha256"
                    )
                    if pitcher_id is not None:
                        try:
                            valid_id = int(pitcher_id) > 0
                        except (TypeError, ValueError):
                            valid_id = False
                        if not valid_id:
                            issues.append(
                                EvidenceIssue(
                                    "provenance",
                                    game_pk,
                                    f"Invalid {side} starter MLB person ID",
                                    int(event["sequence"]),
                                )
                            )
                        if not starter_hash or not _HASH_PATTERN.fullmatch(
                            str(starter_hash)
                        ):
                            issues.append(
                                EvidenceIssue(
                                    "provenance",
                                    game_pk,
                                    f"{side.title()} starter identity lacks an immutable snapshot SHA-256",
                                    int(event["sequence"]),
                                )
                            )
                    elif starter_hash is not None:
                        issues.append(
                            EvidenceIssue(
                                "provenance",
                                game_pk,
                                f"{side.title()} starter snapshot exists without a starter ID",
                                int(event["sequence"]),
                            )
                        )

        latest_prediction = _latest(game_events, "prediction")
        latest_close = _latest(game_events, "closing_line")
        latest_outcome = _latest(game_events, "outcome")
        if latest_prediction is not None:
            latest_payload = latest_prediction.get("payload") or {}
            starter_ids = [
                latest_payload.get("away_starter_id"),
                latest_payload.get("home_starter_id"),
            ]
            starter_hashes = [
                latest_payload.get("away_starter_snapshot_sha256"),
                latest_payload.get("home_starter_snapshot_sha256"),
            ]
            if any(value is not None for value in starter_ids):
                starter_identity_games += 1
            valid_hash_count = sum(
                bool(value and _HASH_PATTERN.fullmatch(str(value)))
                for value in starter_hashes
            )
            if valid_hash_count == 2:
                starter_stats_complete_games += 1
            elif valid_hash_count == 1:
                starter_stats_partial_games += 1
        if latest_prediction is not None and latest_outcome is not None:
            eligible_games += 1
            graded_games += 1
            if latest_close is not None:
                games_with_closing_line += 1
            prediction_payload = latest_prediction["payload"]
            outcome_payload = latest_outcome["payload"]
            row = {
                "game_pk": game_pk,
                "home_probability": float(prediction_payload["home_probability"]),
                "base_shadow_home_probability": prediction_payload.get(
                    "base_shadow_home_probability"
                ),
                "production_home_probability": prediction_payload.get(
                    "production_home_probability"
                ),
                "home_won": int(bool(outcome_payload["home_won"])),
                "model_version": prediction_payload.get("model_version"),
                "candidate_commit": prediction_payload.get("candidate_commit"),
                "adaptive_overlay_sha256": prediction_payload.get(
                    "adaptive_overlay_sha256"
                ),
                "offered_home_implied": prediction_payload.get("offered_home_implied"),
                "closing_home_implied": (
                    latest_close["payload"].get("closing_home_implied")
                    if latest_close is not None
                    else None
                ),
            }
            diagnostics_rows.append(row)

        if len(outcome_events) > 1:
            outcomes = {int(bool(event["payload"]["home_won"])) for event in outcome_events}
            if len(outcomes) > 1:
                issues.append(
                    EvidenceIssue(
                        "schedule_integrity",
                        game_pk,
                        "Conflicting outcome events for one gamePk",
                    )
                )

    category_counts: dict[str, int] = {}
    for issue in issues:
        category_counts[issue.category] = category_counts.get(issue.category, 0) + 1

    diagnostics: dict[str, Any] = {
        "games": len(by_game),
        "events": len(events),
        "predictions": prediction_count,
        "graded_games": graded_games,
        "games_with_closing_line": games_with_closing_line,
        "starter_identity_games": starter_identity_games,
        "starter_stats_complete_games": starter_stats_complete_games,
        "starter_stats_partial_games": starter_stats_partial_games,
    }
    if diagnostics_rows:
        probabilities = [row["home_probability"] for row in diagnostics_rows]
        outcomes = [row["home_won"] for row in diagnostics_rows]
        diagnostics["brier"] = sum(
            (probability - outcome) ** 2
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        ) / len(outcomes)
        diagnostics["accuracy"] = sum(
            int((probability >= 0.5) == bool(outcome))
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        ) / len(outcomes)
        diagnostics["log_loss"] = -sum(
            outcome * math.log(min(max(probability, 1e-6), 1 - 1e-6))
            + (1 - outcome)
            * math.log(min(max(1 - probability, 1e-6), 1 - 1e-6))
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        ) / len(outcomes)

        probability_tracks: dict[str, dict[str, float | int]] = {}
        for label, key in (
            ("production_v2_3_3", "production_home_probability"),
            ("base_v2_4", "base_shadow_home_probability"),
            ("adaptive_v2_4", "home_probability"),
        ):
            track_rows = [row for row in diagnostics_rows if row.get(key) is not None]
            if not track_rows:
                continue
            track_p = [float(row[key]) for row in track_rows]
            track_y = [int(row["home_won"]) for row in track_rows]
            probability_tracks[label] = {
                "n": len(track_rows),
                "accuracy": sum(
                    int((probability >= 0.5) == bool(outcome))
                    for probability, outcome in zip(track_p, track_y, strict=True)
                )
                / len(track_rows),
                "brier": sum(
                    (probability - outcome) ** 2
                    for probability, outcome in zip(track_p, track_y, strict=True)
                )
                / len(track_rows),
                "log_loss": -sum(
                    outcome * math.log(min(max(probability, 1e-6), 1 - 1e-6))
                    + (1 - outcome)
                    * math.log(min(max(1 - probability, 1e-6), 1 - 1e-6))
                    for probability, outcome in zip(track_p, track_y, strict=True)
                )
                / len(track_rows),
            }
        diagnostics["probability_tracks"] = probability_tracks

        cohorts: dict[str, int] = {}
        for row in diagnostics_rows:
            key = "|".join(
                [
                    str(row.get("model_version") or "unknown"),
                    str(row.get("candidate_commit") or "unknown"),
                    str(row.get("adaptive_overlay_sha256") or "none"),
                ]
            )
            cohorts[key] = cohorts.get(key, 0) + 1
        diagnostics["candidate_cohorts"] = cohorts
        clv_rows = [
            row
            for row in diagnostics_rows
            if row["offered_home_implied"] is not None
            and row["closing_home_implied"] is not None
        ]
        if clv_rows:
            diagnostics["mean_home_probability_clv"] = sum(
                float(row["closing_home_implied"])
                - float(row["offered_home_implied"])
                for row in clv_rows
            ) / len(clv_rows)

    schedule_errors = category_counts.get("schedule_integrity", 0)
    leakage_errors = category_counts.get("target_leakage", 0)
    provenance_errors = category_counts.get("provenance", 0)
    integrity_errors = category_counts.get("ledger_integrity", 0)

    if integrity_errors:
        prospective_gate = _gate("FAIL", None, "Ledger integrity verification failed.")
    elif eligible_games >= minimum_prospective_games:
        prospective_gate = _gate(
            "PASS",
            eligible_games,
            f"Collected at least {minimum_prospective_games} graded prospective games.",
        )
    else:
        prospective_gate = _gate(
            "PENDING",
            eligible_games,
            f"Collected {eligible_games} of {minimum_prospective_games} required games.",
        )

    if integrity_errors:
        closing_gate = _gate("FAIL", None, "Ledger integrity verification failed.")
    elif graded_games == 0:
        closing_gate = _gate("PENDING", None, "No graded prospective games yet.")
    else:
        closing_complete = games_with_closing_line == graded_games
        closing_gate = _gate(
            "PASS" if closing_complete else "FAIL",
            closing_complete,
            f"Closing line present for {games_with_closing_line}/{graded_games} graded games.",
        )

    if not events:
        schedule_gate = _gate("PENDING", None, "No prospective events have been recorded.")
    else:
        schedule_gate = _gate(
            "PASS" if ledger_integrity and schedule_errors == 0 else "FAIL",
            ledger_integrity and schedule_errors == 0,
            f"Detected {schedule_errors} schedule-integrity issue(s).",
        )

    if prediction_count == 0:
        leakage_gate = _gate("PENDING", None, "No prediction events have been recorded.")
        provenance_gate = _gate("PENDING", None, "No prediction events have been recorded.")
    else:
        leakage_gate = _gate(
            "PASS" if leakage_errors == 0 and integrity_errors == 0 else "FAIL",
            leakage_errors == 0 and integrity_errors == 0,
            f"Detected {leakage_errors} target-leakage issue(s).",
        )
        provenance_gate = _gate(
            "PASS" if provenance_errors == 0 and integrity_errors == 0 else "FAIL",
            provenance_errors == 0 and integrity_errors == 0,
            f"Detected {provenance_errors} provenance issue(s).",
        )

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "ledger": str(path),
        "ledger_exists": path.exists(),
        "ledger_sha256": ledger.sha256(),
        "summary": diagnostics,
        "gate_evidence": {
            "prospective_games": prospective_gate,
            "closing_line_value_tracking": closing_gate,
            "schedule_integrity_passed": schedule_gate,
            "target_leakage_tests_passed": leakage_gate,
            "point_in_time_provenance": provenance_gate,
        },
        "issue_counts": category_counts,
        "issues": [issue.to_record() for issue in issues],
    }


def write_evidence_report(
    ledger_path: str | Path,
    output_path: str | Path,
    *,
    minimum_prospective_games: int = 500,
    required_provenance_keys: Iterable[str] = (
        "schedule",
        "live_feed",
        "pitcher_stats",
        "market_input",
    ),
) -> dict[str, Any]:
    report = audit_prospective_evidence(
        ledger_path,
        minimum_prospective_games=minimum_prospective_games,
        required_provenance_keys=required_provenance_keys,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
