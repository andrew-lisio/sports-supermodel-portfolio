from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from .evidence import ProspectiveEvidenceLedger, write_evidence_report
from .live_mlb import MLBStatsHTTPClient
from .market import no_vig_probabilities


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-evidence",
        description="Record and audit point-in-time V2.4 prospective evidence.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/evidence.yaml"),
    )
    parser.add_argument("--ledger", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    close = subparsers.add_parser("record-close", help="Append a pre-start closing line.")
    close.add_argument("--game-pk", type=int, required=True)
    close.add_argument("--scheduled-start", required=True)
    close.add_argument("--captured-at", default=None)
    close.add_argument("--away-odds", type=int, required=True)
    close.add_argument("--home-odds", type=int, required=True)
    close.add_argument("--source", default="manual_closing_line")

    outcome = subparsers.add_parser("record-outcome", help="Append a final binary outcome.")
    outcome.add_argument("--game-pk", type=int, required=True)
    outcome.add_argument("--scheduled-start", required=True)
    outcome.add_argument("--recorded-at", default=None)
    outcome.add_argument("--home-won", type=int, choices=[0, 1], required=True)
    outcome.add_argument("--source", default="official_result")

    official_outcome = subparsers.add_parser(
        "record-official-outcome",
        help="Fetch a final MLB live feed and append its outcome.",
    )
    official_outcome.add_argument("--game-pk", type=int, required=True)
    official_outcome.add_argument("--scheduled-start", required=True)
    official_outcome.add_argument("--recorded-at", default=None)
    official_outcome.add_argument("--source", default="mlb_stats_api:v1.1/game/feed/live")

    prediction = subparsers.add_parser(
        "record-prediction",
        help="Append a prediction from an explicit JSON payload.",
    )
    prediction.add_argument("--game-pk", type=int, required=True)
    prediction.add_argument("--scheduled-start", required=True)
    prediction.add_argument("--captured-at", default=None)
    prediction.add_argument("--payload", type=Path, required=True)
    prediction.add_argument("--provenance", type=Path, required=True)
    prediction.add_argument("--snapshot-sha256", required=True)
    prediction.add_argument("--source", default="manual_prediction_import")

    audit = subparsers.add_parser("audit", help="Write a promotion-gate evidence report.")
    audit.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    audit.add_argument("--minimum-prospective-games", type=int, default=None)
    audit.add_argument(
        "--required-provenance-key",
        action="append",
        dest="required_provenance_keys",
        default=None,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config: dict[str, Any] = {}
    if args.config.exists():
        loaded = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Evidence config must be a YAML mapping")
        config = loaded
    ledger_path = args.ledger or Path(
        str(config.get("ledger", "runtime/evidence/prospective.jsonl"))
    )
    ledger = ProspectiveEvidenceLedger(ledger_path)

    if args.command == "record-close":
        away_implied, home_implied = no_vig_probabilities(args.away_odds, args.home_odds)
        event = ledger.append(
            event_type="closing_line",
            game_pk=args.game_pk,
            recorded_at=args.captured_at or _now_utc(),
            scheduled_start=args.scheduled_start,
            source=args.source,
            payload={
                "away_odds": args.away_odds,
                "home_odds": args.home_odds,
                "closing_away_implied": away_implied,
                "closing_home_implied": home_implied,
            },
        )
        print(json.dumps(event, indent=2))
        return 0

    if args.command == "record-outcome":
        event = ledger.append(
            event_type="outcome",
            game_pk=args.game_pk,
            recorded_at=args.recorded_at or _now_utc(),
            scheduled_start=args.scheduled_start,
            source=args.source,
            payload={"home_won": args.home_won},
        )
        print(json.dumps(event, indent=2))
        return 0

    if args.command == "record-official-outcome":
        feed = MLBStatsHTTPClient().live_feed(args.game_pk)
        status = (feed.get("gameData") or {}).get("status") or {}
        state = " ".join(
            str(status.get(key) or "")
            for key in ("abstractGameState", "detailedState")
        ).lower()
        if "final" not in state and "completed" not in state:
            raise ValueError(f"game_pk {args.game_pk} is not final")
        teams = ((feed.get("liveData") or {}).get("linescore") or {}).get("teams") or {}
        away_runs = (teams.get("away") or {}).get("runs")
        home_runs = (teams.get("home") or {}).get("runs")
        if away_runs is None or home_runs is None:
            raise ValueError("Final live feed does not contain both team run totals")
        event = ledger.append(
            event_type="outcome",
            game_pk=args.game_pk,
            recorded_at=args.recorded_at or _now_utc(),
            scheduled_start=args.scheduled_start,
            source=args.source,
            payload={
                "away_runs": int(away_runs),
                "home_runs": int(home_runs),
                "home_won": int(home_runs > away_runs),
                "status": status.get("detailedState") or status.get("abstractGameState"),
            },
        )
        print(json.dumps(event, indent=2))
        return 0

    if args.command == "record-prediction":
        event = ledger.append(
            event_type="prediction",
            game_pk=args.game_pk,
            recorded_at=args.captured_at or _now_utc(),
            scheduled_start=args.scheduled_start,
            source=args.source,
            payload=_load_mapping(args.payload),
            provenance=_load_mapping(args.provenance),
            snapshot_sha256=args.snapshot_sha256,
        )
        print(json.dumps(event, indent=2))
        return 0

    required_keys = args.required_provenance_keys or list(
        config.get(
            "required_provenance_keys",
            ["schedule", "live_feed", "pitcher_stats", "market_input"],
        )
    )
    output_path = args.output or Path(
        str(config.get("report", "runtime/evidence/evidence_report.json"))
    )
    minimum_games = args.minimum_prospective_games
    if minimum_games is None:
        minimum_games = int(config.get("minimum_prospective_games", 500))
    report = write_evidence_report(
        ledger_path,
        output_path,
        minimum_prospective_games=minimum_games,
        required_provenance_keys=required_keys,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
