"""Sports SuperModel public package interface."""

from .game_registry import (
    GameRecord,
    ImmutableSnapshotStore,
    ScheduleIntegrityError,
    index_by_game_pk,
    parse_mlb_schedule,
)
from .market import (
    american_implied_probability,
    american_to_decimal,
    combine_american_odds,
    no_vig_probabilities,
    probability_to_american,
)
from .mlb_v2 import (
    LIVE_FEATURES,
    V2Ensemble,
    build_pregame_features,
    load_team_logs,
    reconstruct_games,
    replay_dates,
    walk_forward_trials,
)
from .providers import OfficialScheduleSnapshotProvider, PregameContext, ProviderPipeline

__version__ = "2.3.1"

__all__ = [
    "__version__",
    "GameRecord",
    "ImmutableSnapshotStore",
    "ScheduleIntegrityError",
    "index_by_game_pk",
    "parse_mlb_schedule",
    "OfficialScheduleSnapshotProvider",
    "PregameContext",
    "ProviderPipeline",
    "american_implied_probability",
    "american_to_decimal",
    "combine_american_odds",
    "no_vig_probabilities",
    "probability_to_american",
    "load_team_logs",
    "reconstruct_games",
    "build_pregame_features",
    "walk_forward_trials",
    "replay_dates",
    "V2Ensemble",
    "LIVE_FEATURES",
]
