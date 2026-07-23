"""Non-causal feature-group sensitivity diagnostics for V2.4.

The diagnostics in this module deliberately do not alter a prediction. They compare
an already-fitted model's normal probability with a counterfactual probability after
one registered feature group is replaced by training-reference values. The resulting
change is useful for explanation and debugging, but it is not a causal contribution
and the group effects are not expected to add up to the final probability.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import numpy as np
import pandas as pd


class AttributionInputError(ValueError):
    """Raised when sensitivity diagnostics receive an invalid feature contract."""


def leave_group_at_reference_sensitivity(
    frame: pd.DataFrame,
    *,
    baseline_probability: Sequence[float] | np.ndarray,
    predict_probability: Callable[[pd.DataFrame], Sequence[float] | np.ndarray],
    feature_groups: Mapping[str, Sequence[str]],
    reference_values: Mapping[str, float],
) -> dict[str, np.ndarray]:
    """Measure probability sensitivity to neutralizing each feature group.

    A positive value means the observed feature group raises the modeled probability
    relative to replacing that group with its training-reference values. A negative
    value means the observed group lowers the modeled probability. The returned values
    retain the model's native team orientation.
    """

    baseline = np.asarray(baseline_probability, dtype=float)
    if baseline.ndim != 1 or len(baseline) != len(frame):
        raise AttributionInputError(
            "baseline_probability must be one-dimensional and match the frame length"
        )

    output: dict[str, np.ndarray] = {}
    for group_name, feature_names in feature_groups.items():
        names = list(feature_names)
        if not names:
            continue
        missing_columns = [name for name in names if name not in frame.columns]
        if missing_columns:
            raise AttributionInputError(
                f"Feature group {group_name!r} references missing columns: "
                + ", ".join(missing_columns)
            )
        missing_references = [name for name in names if name not in reference_values]
        if missing_references:
            raise AttributionInputError(
                f"Feature group {group_name!r} has no reference values for: "
                + ", ".join(missing_references)
            )

        neutral = frame.copy()
        for name in names:
            neutral[name] = float(reference_values[name])
        neutral_probability = np.asarray(predict_probability(neutral), dtype=float)
        if neutral_probability.shape != baseline.shape:
            raise AttributionInputError(
                f"Predictor returned the wrong shape while neutralizing {group_name!r}"
            )
        output[group_name] = baseline - neutral_probability

    return output
