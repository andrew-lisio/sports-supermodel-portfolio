from __future__ import annotations

import argparse
import json

from .totals_model import build_line_frontier, simulate_totals_candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-totals",
        description="Run the shadow-only overdispersed totals candidate.",
    )
    parser.add_argument("--away-mean", type=float, required=True)
    parser.add_argument("--home-mean", type=float, required=True)
    parser.add_argument("--simulations", type=int, default=100_000)
    parser.add_argument("--lines", default="7.5,8,8.5,9,9.5")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    draws = simulate_totals_candidate(
        args.away_mean,
        args.home_mean,
        simulations=args.simulations,
    )
    lines = [float(value.strip()) for value in args.lines.split(",") if value.strip()]
    payload = {
        "status": draws.status,
        "version": draws.version,
        "simulations": draws.simulations,
        "mean_away_runs": float(draws.away_runs.mean()),
        "mean_home_runs": float(draws.home_runs.mean()),
        "score_correlation": float(__import__("numpy").corrcoef(draws.away_runs, draws.home_runs)[0, 1]),
        "frontier": [point.to_record() for point in build_line_frontier(draws, lines=lines)],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
