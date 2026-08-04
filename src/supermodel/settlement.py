from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .evidence import ProspectiveEvidenceLedger
from .market import american_to_decimal


@dataclass(frozen=True)
class SettledPrediction:
    game_pk: int
    away_team: str
    home_team: str
    home_won: int
    production_home_probability: float
    shadow_home_probability: float
    production_pick: str
    shadow_pick: str
    production_correct: bool
    shadow_correct: bool
    production_brier: float
    shadow_brier: float
    production_log_loss: float
    shadow_log_loss: float
    offered_pick_odds: int | None
    realized_roi: float | None
    closing_line_value: float | None
    selection_status: str | None
    series_context_status: str | None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceSummary:
    status: str
    generated_at_utc: str
    settled_games: int
    production_accuracy: float | None
    shadow_accuracy: float | None
    production_brier: float | None
    shadow_brier: float | None
    production_log_loss: float | None
    shadow_log_loss: float | None
    recommendation_roi: float | None
    average_closing_line_value: float | None
    production_shadow_disagreements: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _latest(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    candidates = [event for event in events if event.get("event_type") == event_type]
    if not candidates:
        return None
    return max(candidates, key=lambda event: (event.get("recorded_at", ""), event.get("sequence", 0)))


def _log_loss(probability: float, outcome: int) -> float:
    p = float(np.clip(probability, 1e-8, 1 - 1e-8))
    return float(-(outcome * math.log(p) + (1 - outcome) * math.log(1 - p)))


def _realized_roi(*, won: bool, american_odds: int | None) -> float | None:
    if american_odds is None:
        return None
    return american_to_decimal(int(american_odds)) - 1.0 if won else -1.0


def settle_evidence_events(events: Iterable[Mapping[str, Any]]) -> tuple[SettledPrediction, ...]:
    by_game: dict[int, list[dict[str, Any]]] = {}
    for raw in events:
        event = dict(raw)
        by_game.setdefault(int(event["game_pk"]), []).append(event)

    settled: list[SettledPrediction] = []
    for game_pk, game_events in sorted(by_game.items()):
        prediction = _latest(game_events, "prediction")
        outcome = _latest(game_events, "outcome")
        if prediction is None or outcome is None:
            continue
        closing = _latest(game_events, "closing_line")
        pred = prediction.get("payload") or {}
        result = outcome.get("payload") or {}
        home_won = int(bool(result["home_won"]))
        production_home = float(pred["production_home_probability"])
        shadow_home = float(pred["home_probability"])
        away_team = str(pred["away_team"])
        home_team = str(pred["home_team"])
        production_pick = home_team if production_home >= 0.5 else away_team
        shadow_pick = home_team if shadow_home >= 0.5 else away_team
        actual_pick = home_team if home_won else away_team
        offered_odds = (
            int(pred.get("home_odds"))
            if production_pick == home_team and pred.get("home_odds") is not None
            else int(pred.get("away_odds"))
            if pred.get("away_odds") is not None
            else None
        )
        closing_value: float | None = None
        if closing is not None:
            closing_home = float((closing.get("payload") or {})["closing_home_implied"])
            offered_home = pred.get("offered_home_implied")
            if offered_home is not None:
                # Positive means the recommended side became more expensive by close.
                closing_value = (
                    closing_home - float(offered_home)
                    if production_pick == home_team
                    else float(offered_home) - closing_home
                )
        won = production_pick == actual_pick
        settled.append(
            SettledPrediction(
                game_pk=game_pk,
                away_team=away_team,
                home_team=home_team,
                home_won=home_won,
                production_home_probability=production_home,
                shadow_home_probability=shadow_home,
                production_pick=production_pick,
                shadow_pick=shadow_pick,
                production_correct=won,
                shadow_correct=shadow_pick == actual_pick,
                production_brier=(production_home - home_won) ** 2,
                shadow_brier=(shadow_home - home_won) ** 2,
                production_log_loss=_log_loss(production_home, home_won),
                shadow_log_loss=_log_loss(shadow_home, home_won),
                offered_pick_odds=offered_odds,
                realized_roi=_realized_roi(won=won, american_odds=offered_odds),
                closing_line_value=closing_value,
                selection_status=pred.get("selection_status"),
                series_context_status=pred.get("series_context_status"),
            )
        )
    return tuple(settled)


def summarize_performance(rows: Iterable[SettledPrediction]) -> PerformanceSummary:
    items = list(rows)
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not items:
        return PerformanceSummary(
            status="NO_SETTLED_GAMES",
            generated_at_utc=generated,
            settled_games=0,
            production_accuracy=None,
            shadow_accuracy=None,
            production_brier=None,
            shadow_brier=None,
            production_log_loss=None,
            shadow_log_loss=None,
            recommendation_roi=None,
            average_closing_line_value=None,
            production_shadow_disagreements=0,
        )
    rois = [item.realized_roi for item in items if item.realized_roi is not None]
    clv = [item.closing_line_value for item in items if item.closing_line_value is not None]
    return PerformanceSummary(
        status="PASS",
        generated_at_utc=generated,
        settled_games=len(items),
        production_accuracy=float(np.mean([item.production_correct for item in items])),
        shadow_accuracy=float(np.mean([item.shadow_correct for item in items])),
        production_brier=float(np.mean([item.production_brier for item in items])),
        shadow_brier=float(np.mean([item.shadow_brier for item in items])),
        production_log_loss=float(np.mean([item.production_log_loss for item in items])),
        shadow_log_loss=float(np.mean([item.shadow_log_loss for item in items])),
        recommendation_roi=float(np.mean(rois)) if rois else None,
        average_closing_line_value=float(np.mean(clv)) if clv else None,
        production_shadow_disagreements=sum(
            item.production_pick != item.shadow_pick for item in items
        ),
    )


def settle_ledger(
    ledger_path: str | Path,
    *,
    output_root: str | Path = "runtime/performance",
) -> tuple[PerformanceSummary, Path]:
    ledger = ProspectiveEvidenceLedger(ledger_path)
    settled = settle_evidence_events(ledger.read(verify=True))
    summary = summarize_performance(settled)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary.to_record(),
        "settled_predictions": [item.to_record() for item in settled],
    }
    latest = root / "latest.json"
    temporary = latest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(latest)
    return summary, latest
