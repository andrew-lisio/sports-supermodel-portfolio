import numpy as np
import pandas as pd
import pytest

from supermodel.feature_attribution import (
    AttributionInputError,
    leave_group_at_reference_sensitivity,
)


def test_leave_group_at_reference_sensitivity_is_directional_and_non_mutating():
    frame = pd.DataFrame({
        "offense": [2.0, -1.0],
        "starter": [1.0, 2.0],
    })
    original = frame.copy(deep=True)

    def predict(target: pd.DataFrame) -> np.ndarray:
        return np.asarray(0.50 + 0.10 * target["offense"] + 0.05 * target["starter"])

    baseline = predict(frame)
    result = leave_group_at_reference_sensitivity(
        frame,
        baseline_probability=baseline,
        predict_probability=predict,
        feature_groups={"offense": ["offense"], "starting_pitcher": ["starter"]},
        reference_values={"offense": 0.0, "starter": 0.0},
    )

    assert np.allclose(result["offense"], [0.20, -0.10])
    assert np.allclose(result["starting_pitcher"], [0.05, 0.10])
    pd.testing.assert_frame_equal(frame, original)


def test_sensitivity_fails_closed_for_missing_columns_or_references():
    frame = pd.DataFrame({"offense": [1.0]})
    def predictor(target):
        return np.asarray([0.5])

    with pytest.raises(AttributionInputError, match="missing columns"):
        leave_group_at_reference_sensitivity(
            frame,
            baseline_probability=[0.5],
            predict_probability=predictor,
            feature_groups={"pitching": ["starter"]},
            reference_values={"starter": 0.0},
        )

    with pytest.raises(AttributionInputError, match="no reference values"):
        leave_group_at_reference_sensitivity(
            frame,
            baseline_probability=[0.5],
            predict_probability=predictor,
            feature_groups={"offense": ["offense"]},
            reference_values={},
        )
