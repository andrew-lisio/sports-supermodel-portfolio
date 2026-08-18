from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .security import launch_readiness


PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT = "ENABLE_PUBLIC_SPORTS_SUPERMODEL"


class PublicDeploymentState(StrEnum):
    DORMANT = "DORMANT"
    ENABLED = "ENABLED"


class PublicDeploymentDisabled(RuntimeError):
    """Raised when a hosted/public service is started without explicit activation."""


@dataclass(frozen=True)
class PublicDeploymentSettings:
    enabled: bool = False
    acknowledgement: str = ""
    environment: str = "development"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "PublicDeploymentSettings":
        values = environ if environ is not None else os.environ
        enabled = str(values.get("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED", "0"))
        return cls(
            enabled=enabled.strip().casefold() in {"1", "true", "yes", "on"},
            acknowledgement=str(
                values.get("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK", "")
            ).strip(),
            environment=str(values.get("SPORTS_SUPERMODEL_ENV", "development"))
            .strip()
            .lower(),
        )

    @property
    def state(self) -> PublicDeploymentState:
        return (
            PublicDeploymentState.ENABLED
            if self.enabled
            else PublicDeploymentState.DORMANT
        )

    @property
    def acknowledgement_valid(self) -> bool:
        return self.acknowledgement == PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT

    def to_record(self) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "enabled": self.enabled,
            "environment": self.environment,
            "acknowledgement_configured": bool(self.acknowledgement),
            "acknowledgement_valid": self.acknowledgement_valid,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deployment_plan() -> dict[str, Any]:
    """Return the dormant-to-public activation plan without changing any infrastructure."""

    return {
        "status": "PLAN_ONLY",
        "side_effects": False,
        "summary": (
            "The repository contains dormant public-deployment framework. No service, "
            "database, bucket, domain, or public endpoint is created by this command."
        ),
        "activation_sequence": [
            "Provision PostgreSQL and S3-compatible object storage when deployment is approved.",
            "Store provider and platform secrets in the hosting provider secret manager.",
            "Run storage migrations, backup verification, and a staging readiness check.",
            "Set SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED=1.",
            (
                "Set SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK="
                f"{PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT}."
            ),
            "Start only the intended deployment profile and verify health/readiness endpoints.",
        ],
        "required_activation_variables": {
            "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED": "1",
            "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK": (
                PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT
            ),
        },
    }


def public_readiness_report(
    *,
    settings: PublicDeploymentSettings | None = None,
    require_odds: bool = True,
) -> dict[str, Any]:
    active = settings or PublicDeploymentSettings.from_env()
    if not active.enabled:
        return {
            "status": "DORMANT",
            "checked_at_utc": _utc_now(),
            "public_deployment": active.to_record(),
            "failures": [],
            "warnings": ["PUBLIC_DEPLOYMENT_NOT_ENABLED"],
            "side_effects": False,
        }

    failures: list[str] = []
    warnings: list[str] = []
    if not active.acknowledgement_valid:
        failures.append("PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT_INVALID")
    if active.environment not in {"staging", "production"}:
        failures.append("PUBLIC_DEPLOYMENT_REQUIRES_STAGING_OR_PRODUCTION_ENV")

    platform: dict[str, Any]
    try:
        platform = launch_readiness(require_odds=require_odds)
    except (RuntimeError, ValueError) as exc:
        platform = {
            "status": "FAIL",
            "failures": ["PLATFORM_CONFIGURATION_INVALID"],
            "warnings": [],
            "configuration_error": str(exc),
        }
    failures.extend(str(item) for item in platform.get("failures", []))
    warnings.extend(str(item) for item in platform.get("warnings", []))
    return {
        "status": "READY" if not failures else "NOT_READY",
        "checked_at_utc": _utc_now(),
        "public_deployment": active.to_record(),
        "failures": sorted(set(failures)),
        "warnings": sorted(set(warnings)),
        "platform": platform,
        "side_effects": False,
    }


def guard_public_service(
    service: str,
    *,
    settings: PublicDeploymentSettings | None = None,
    require_ready: bool = True,
    require_odds: bool = True,
) -> dict[str, Any]:
    active = settings or PublicDeploymentSettings.from_env()
    if not active.enabled:
        raise PublicDeploymentDisabled(
            f"Public service {service!r} is dormant. Set "
            "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED=1 only when deployment is approved."
        )
    report = public_readiness_report(settings=active, require_odds=require_odds)
    if require_ready and report["status"] != "READY":
        raise RuntimeError(
            f"Public service {service!r} failed readiness: "
            + ", ".join(report.get("failures", []))
        )
    return {
        "status": "PASS",
        "service": str(service),
        "checked_at_utc": _utc_now(),
        "public_deployment": active.to_record(),
        "readiness": report,
    }


def write_readiness_snapshot(
    destination: str | Path,
    *,
    settings: PublicDeploymentSettings | None = None,
    require_odds: bool = True,
) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = public_readiness_report(settings=settings, require_odds=require_odds)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
