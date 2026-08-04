from __future__ import annotations

import argparse
import json

from .security import launch_readiness
from .service_runtime import build_health


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-ops",
        description="Run launch-readiness and service health audits.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("readiness")
    ready.add_argument("--allow-missing-odds", action="store_true")
    health = sub.add_parser("health")
    health.add_argument("--service", default="ops")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "readiness":
        payload = launch_readiness(require_odds=not args.allow_missing_odds)
    else:
        payload = build_health(args.service).to_record()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
