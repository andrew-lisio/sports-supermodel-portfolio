"""CPU-budgeted execution profiles for V2.4 model and validation workloads.

The accelerated profile parallelizes independent work while keeping each native model
on a bounded thread budget.  This prevents the seven-model ensemble, matched
baseline/candidate validation, and multi-candidate experiments from multiplying into
unbounded nested thread pools.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Workload = Literal["live", "validation", "experiment"]


@dataclass(frozen=True)
class ExecutionProfile:
    """Raw execution limits loaded from ``config/execution.yaml``."""

    name: str
    total_workers: int | str = "auto"
    max_model_workers: int = 7
    comparison_workers: int = 1
    max_candidate_workers: int = 1
    estimator_threads: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.total_workers, str) and self.total_workers != "auto":
            raise ValueError("total_workers must be a positive integer or 'auto'")
        if isinstance(self.total_workers, int) and self.total_workers <= 0:
            raise ValueError("total_workers must be positive")
        for field_name in (
            "max_model_workers",
            "comparison_workers",
            "max_candidate_workers",
            "estimator_threads",
        ):
            if int(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True)
class ExecutionPlan:
    """Resolved worker allocation for one workload."""

    profile: str
    workload: Workload
    cpu_count: int
    total_workers: int
    model_workers: int
    estimator_threads: int
    comparison_workers: int = 1
    candidate_workers: int = 1

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def available_cpu_count() -> int:
    """Return the CPU count visible to this process, respecting affinity when possible."""

    try:
        affinity = os.sched_getaffinity(0)
    except (AttributeError, OSError):
        affinity = None
    if affinity:
        return max(1, len(affinity))
    return max(1, os.cpu_count() or 1)


def load_execution_profile(
    path: str | Path = "config/execution.yaml",
    *,
    profile: str | None = None,
) -> ExecutionProfile:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = document.get("profiles", {})
    selected_name = profile or document.get("default_profile")
    if not selected_name:
        raise ValueError("Execution config must define default_profile or an explicit profile")
    if selected_name not in profiles:
        available = ", ".join(sorted(profiles)) or "none"
        raise ValueError(
            f"Unknown execution profile {selected_name!r}. Available profiles: {available}"
        )
    raw = profiles[selected_name] or {}
    return ExecutionProfile(
        name=str(selected_name),
        total_workers=raw.get("total_workers", "auto"),
        max_model_workers=int(raw.get("max_model_workers", 7)),
        comparison_workers=int(raw.get("comparison_workers", 1)),
        max_candidate_workers=int(raw.get("max_candidate_workers", 1)),
        estimator_threads=int(raw.get("estimator_threads", 1)),
    )


def resolve_execution_plan(
    profile: ExecutionProfile,
    *,
    workload: Workload,
    total_workers: int | None = None,
    candidate_count: int | None = None,
) -> ExecutionPlan:
    """Allocate a bounded worker budget without nested oversubscription."""

    cpu_count = available_cpu_count()
    configured_total = cpu_count if profile.total_workers == "auto" else int(profile.total_workers)
    resolved_total = int(total_workers) if total_workers is not None else configured_total
    if resolved_total <= 0:
        raise ValueError("total_workers override must be positive")
    resolved_total = max(1, min(resolved_total, cpu_count))

    comparison_workers = 1
    candidate_workers = 1
    if workload == "validation":
        comparison_workers = min(profile.comparison_workers, 2, resolved_total)
        task_workers = comparison_workers
    elif workload == "experiment":
        count = max(1, int(candidate_count or 1))
        candidate_workers = min(profile.max_candidate_workers, count, resolved_total)
        task_workers = candidate_workers
    elif workload == "live":
        task_workers = 1
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"Unsupported workload: {workload}")

    workers_per_task = max(1, resolved_total // task_workers)
    model_workers = min(profile.max_model_workers, 7, workers_per_task)

    return ExecutionPlan(
        profile=profile.name,
        workload=workload,
        cpu_count=cpu_count,
        total_workers=resolved_total,
        model_workers=max(1, model_workers),
        estimator_threads=profile.estimator_threads,
        comparison_workers=comparison_workers,
        candidate_workers=candidate_workers,
    )
