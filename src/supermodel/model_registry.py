"""Canonical registry for the complete seven-model MLB winner ensemble."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
from typing import Any, Mapping


@dataclass(frozen=True)
class ModelRegistration:
    key: str
    display_name: str
    family: str
    dependency: str


MODEL_REGISTRY: tuple[ModelRegistration, ...] = (
    ModelRegistration("logistic", "Logistic Regression", "linear", "scikit-learn"),
    ModelRegistration("random_forest", "Random Forest", "tree_ensemble", "scikit-learn"),
    ModelRegistration("neural_network", "Neural Network", "neural", "scikit-learn"),
    ModelRegistration("elo_pyth", "Elo / Pythagorean", "baseball_rating", "built-in"),
    ModelRegistration("xgboost", "XGBoost", "gradient_boosting", "xgboost"),
    ModelRegistration("lightgbm", "LightGBM", "gradient_boosting", "lightgbm"),
    ModelRegistration("catboost", "CatBoost", "gradient_boosting", "catboost"),
)
MODEL_ORDER: tuple[str, ...] = tuple(item.key for item in MODEL_REGISTRY)
MODEL_DISPLAY_NAMES: dict[str, str] = {
    item.key: item.display_name for item in MODEL_REGISTRY
}
EXPECTED_MODEL_COUNT = len(MODEL_REGISTRY)


class ModelRegistryError(RuntimeError):
    """Raised when the runtime ensemble does not match the frozen seven-model registry."""


def validate_runtime_models(models: Mapping[str, Any]) -> None:
    runtime_keys = tuple(models)
    missing = [name for name in MODEL_ORDER if name not in models]
    unexpected = [name for name in runtime_keys if name not in MODEL_ORDER]
    if missing or unexpected:
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise ModelRegistryError(
            "Runtime model set does not match the seven-model registry (" + "; ".join(detail) + ")"
        )
    if runtime_keys != MODEL_ORDER:
        raise ModelRegistryError(
            "Runtime model order differs from the canonical registry: "
            f"expected {MODEL_ORDER}, observed {runtime_keys}"
        )


def _dependency_version(dependency: str) -> str:
    if dependency == "built-in":
        return "built-in"
    try:
        return metadata.version(dependency)
    except metadata.PackageNotFoundError:
        return "missing"


def registry_snapshot() -> dict[str, Any]:
    return {
        "expected_model_count": EXPECTED_MODEL_COUNT,
        "model_order": list(MODEL_ORDER),
        "models": [
            {
                **asdict(item),
                "dependency_version": _dependency_version(item.dependency),
            }
            for item in MODEL_REGISTRY
        ],
    }
