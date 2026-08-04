from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .storage import create_simulation_snapshot_store


def game_analysis_records(
    *,
    event_date: str,
    simulation_store_root: str | Path = "runtime/simulations",
) -> list[dict[str, Any]]:
    store = create_simulation_snapshot_store(simulation_store_root)
    production = {
        item.game_pk: item
        for item in store.list_latest(event_date=event_date, model_track="production")
    }
    shadow = {
        item.game_pk: item
        for item in store.list_latest(event_date=event_date, model_track="shadow")
    }
    records: list[dict[str, Any]] = []
    for game_pk, snapshot in sorted(production.items()):
        candidate = shadow.get(game_pk)
        production_away = (
            float(snapshot.away_win_probability)
            if snapshot.away_win_probability is not None
            else float(np.mean(snapshot.away_runs > snapshot.home_runs))
        )
        shadow_away = (
            float(candidate.away_win_probability)
            if candidate is not None and candidate.away_win_probability is not None
            else None
        )
        component_votes = {
            name: snapshot.away_team if probability >= 0.5 else snapshot.home_team
            for name, probability in snapshot.component_probabilities.items()
        }
        records.append(
            {
                "game_pk": game_pk,
                "away_team": snapshot.away_team,
                "home_team": snapshot.home_team,
                "production_away_probability": production_away,
                "production_home_probability": 1.0 - production_away,
                "shadow_away_probability": shadow_away,
                "shadow_home_probability": 1.0 - shadow_away if shadow_away is not None else None,
                "production_shadow_delta": (
                    shadow_away - production_away if shadow_away is not None else None
                ),
                "projected_away_runs": float(snapshot.away_runs.mean()),
                "projected_home_runs": float(snapshot.home_runs.mean()),
                "component_votes": component_votes,
                "model_overlap": max(
                    sum(value == snapshot.away_team for value in component_votes.values()),
                    sum(value == snapshot.home_team for value in component_votes.values()),
                ),
                "model_count": len(component_votes),
                "selection_status": snapshot.metadata.get("selection_status"),
                "selection_reasons": snapshot.metadata.get("selection_reasons"),
                "series_context_summary": snapshot.metadata.get("series_context_summary"),
                "live_context_status": snapshot.metadata.get("live_context_status"),
                "lineups_confirmed": snapshot.metadata.get("lineups_confirmed"),
                "history_freshness_status": snapshot.metadata.get("history_freshness_status"),
                "created_at": snapshot.created_at,
                "model_version": snapshot.model_version,
                "git_commit": snapshot.git_commit,
                "simulations": snapshot.simulations,
            }
        )
    return records


def load_performance_payload(
    path: str | Path = "runtime/performance/latest.json",
) -> dict[str, Any] | None:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
