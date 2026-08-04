from __future__ import annotations

import argparse
import json
from pathlib import Path

from .public_readiness import (
    PublicDeploymentDisabled,
    deployment_plan,
    guard_public_service,
    public_readiness_report,
    write_readiness_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-supermodel-public",
        description=(
            "Inspect and guard the dormant public-deployment framework. Commands do not "
            "provision infrastructure or expose the site."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show whether public deployment is dormant or enabled")
    sub.add_parser("plan", help="Print the side-effect-free future activation plan")

    ready = sub.add_parser("readiness", help="Audit public-deployment configuration")
    ready.add_argument("--allow-missing-odds", action="store_true")
    ready.add_argument("--output", type=Path)

    guard = sub.add_parser("guard", help="Fail unless public startup was explicitly enabled")
    guard.add_argument("--service", required=True)
    guard.add_argument("--allow-not-ready", action="store_true")
    guard.add_argument("--allow-missing-odds", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        payload = deployment_plan()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        payload = public_readiness_report(require_odds=False)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "readiness":
        payload = public_readiness_report(require_odds=not args.allow_missing_odds)
        if args.output:
            write_readiness_snapshot(
                args.output,
                require_odds=not args.allow_missing_odds,
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["status"] in {"DORMANT", "READY"} else 2

    try:
        payload = guard_public_service(
            args.service,
            require_ready=not args.allow_not_ready,
            require_odds=not args.allow_missing_odds,
        )
    except PublicDeploymentDisabled as exc:
        print(
            json.dumps(
                {
                    "status": "DORMANT",
                    "service": args.service,
                    "message": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "status": "NOT_READY",
                    "service": args.service,
                    "message": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
