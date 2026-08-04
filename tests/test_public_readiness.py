from pathlib import Path

import pytest

from supermodel.public_readiness import (
    PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT,
    PublicDeploymentDisabled,
    PublicDeploymentSettings,
    deployment_plan,
    guard_public_service,
    public_readiness_report,
)


def test_public_framework_is_dormant_by_default(monkeypatch):
    monkeypatch.delenv("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED", raising=False)
    monkeypatch.delenv("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK", raising=False)
    report = public_readiness_report(require_odds=False)
    assert report["status"] == "DORMANT"
    assert report["side_effects"] is False
    with pytest.raises(PublicDeploymentDisabled):
        guard_public_service("web", require_odds=False)


def test_public_guard_requires_explicit_acknowledgement(monkeypatch):
    monkeypatch.setenv("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED", "1")
    monkeypatch.setenv("SPORTS_SUPERMODEL_ENV", "staging")
    monkeypatch.setenv("SPORTS_SUPERMODEL_ODDS_API_KEY", "configured")
    settings = PublicDeploymentSettings.from_env()
    report = public_readiness_report(settings=settings)
    assert report["status"] == "NOT_READY"
    assert "PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT_INVALID" in report["failures"]


def test_public_guard_passes_only_after_explicit_staging_activation(monkeypatch):
    monkeypatch.setenv("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED", "1")
    monkeypatch.setenv(
        "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK",
        PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT,
    )
    monkeypatch.setenv("SPORTS_SUPERMODEL_ENV", "staging")
    monkeypatch.setenv("SPORTS_SUPERMODEL_ODDS_API_KEY", "configured")
    payload = guard_public_service("web")
    assert payload["status"] == "PASS"
    assert payload["readiness"]["status"] == "READY"


def test_production_readiness_fails_without_shared_storage(monkeypatch):
    monkeypatch.setenv("SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED", "1")
    monkeypatch.setenv(
        "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK",
        PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT,
    )
    monkeypatch.setenv("SPORTS_SUPERMODEL_ENV", "production")
    monkeypatch.setenv("SPORTS_SUPERMODEL_ODDS_API_KEY", "configured")
    monkeypatch.setenv("SPORTS_SUPERMODEL_ADMIN_TOKEN", "configured")
    monkeypatch.setenv("SPORTS_SUPERMODEL_STORAGE_BACKEND", "local")
    monkeypatch.setenv("SPORTS_SUPERMODEL_OBJECT_BACKEND", "local")
    report = public_readiness_report()
    assert report["status"] == "NOT_READY"
    assert "PRODUCTION_REQUIRES_POSTGRES" in report["failures"]
    assert "PRODUCTION_REQUIRES_OBJECT_STORAGE" in report["failures"]


def test_deployment_plan_is_side_effect_free():
    plan = deployment_plan()
    assert plan["status"] == "PLAN_ONLY"
    assert plan["side_effects"] is False
    assert plan["required_activation_variables"][
        "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ACK"
    ] == PUBLIC_DEPLOYMENT_ACKNOWLEDGEMENT


def test_hosted_scripts_and_compose_require_explicit_public_profile():
    root = Path(__file__).resolve().parents[1]
    for script in (
        "run-api.sh",
        "run-combined.sh",
        "run-odds.sh",
        "run-publisher.sh",
        "run-settlement.sh",
        "run-web.sh",
    ):
        text = (root / "deploy" / script).read_text(encoding="utf-8")
        assert "sports-supermodel-public guard" in text
    compose = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert 'profiles: ["public"]' in compose
    assert "SPORTS_SUPERMODEL_PUBLIC_DEPLOYMENT_ENABLED" in compose
