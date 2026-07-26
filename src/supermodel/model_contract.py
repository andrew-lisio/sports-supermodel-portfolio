from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFeatureContract:
    """Versioned feature settings that must remain identical across code paths."""

    name: str
    recent_form_alpha: float
    recent_form_windows: tuple[int, ...]
    include_recent_form_momentum: bool
    include_last_game_context: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("contract name cannot be empty")
        if not 0.0 < self.recent_form_alpha <= 1.0:
            raise ValueError("recent_form_alpha must be in (0, 1]")
        if not self.recent_form_windows:
            raise ValueError("recent_form_windows cannot be empty")
        if tuple(sorted(set(self.recent_form_windows))) != self.recent_form_windows:
            raise ValueError("recent_form_windows must be sorted and unique")


V23_FEATURE_CONTRACT = ModelFeatureContract(
    name="v2.3.3",
    recent_form_alpha=0.18,
    recent_form_windows=(5, 10, 20),
    include_recent_form_momentum=False,
    include_last_game_context=True,
)

# Selected on the locked development folds by the Phase 5A optimizer. This is a
# candidate contract, not a production-promotion declaration; the final holdout
# and prospective gates remain locked/pending.
V24_CANDIDATE_FEATURE_CONTRACT = ModelFeatureContract(
    name="v2.4-candidate-phase3-full-alpha-025",
    recent_form_alpha=0.25,
    recent_form_windows=(3, 5, 10, 20),
    include_recent_form_momentum=True,
    include_last_game_context=True,
)


def active_candidate_contract() -> ModelFeatureContract:
    """Return the frozen V2.4 candidate contract used by historical/live paths."""

    return V24_CANDIDATE_FEATURE_CONTRACT
