from __future__ import annotations

import json

from .model_registry import registry_snapshot
from .mlb_v2 import make_models


def main() -> int:
    models = make_models(model_workers=1, estimator_threads=1)
    payload = registry_snapshot()
    payload["runtime_model_count"] = len(models)
    payload["runtime_model_order"] = list(models)
    payload["status"] = "complete" if len(models) == payload["expected_model_count"] else "incomplete"
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
