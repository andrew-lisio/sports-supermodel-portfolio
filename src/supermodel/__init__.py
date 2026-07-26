from .feature_attribution import (
    AttributionInputError,
    leave_group_at_reference_sensitivity,
)
from .feature_registry import (
    FEATURE_GROUP_ORDER,
    UnclassifiedFeatureError,
    feature_group_for,
    group_feature_names,
    validate_feature_groups,
)
"""Sports SuperModel public package interface."""

from .game_registry import (
    GameRecord,
    ImmutableSnapshotStore,
    ScheduleIntegrityError,
    index_by_game_pk,
    parse_mlb_schedule,
)
from .model_contract import (
    ModelFeatureContract,
    V23_FEATURE_CONTRACT,
    V24_CANDIDATE_FEATURE_CONTRACT,
    active_candidate_contract,
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
from .opponent_form import (
    OpponentAdjustedExperimentPlan,
    OpponentAdjustedFormContract,
    apply_opponent_adjusted_contract,
    load_opponent_adjusted_experiment_plan,
    run_opponent_adjusted_experiments,
)
from .odds_input import (
    ManualMoneyline,
    OddsInputError,
    build_moneyline_template,
    collect_moneylines_interactively,
    load_moneylines,
    moneylines_from_records,
    parse_user_odds,
    write_moneyline_template,
)
from .workflow import (
    CapturedSlate,
    WorkflowResult,
    capture_official_slate,
    evaluate_captured_slate,
)

__version__ = "2.4.0.dev7"

__all__ = [
    "__version__",
    "ModelFeatureContract",
    "V23_FEATURE_CONTRACT",
    "V24_CANDIDATE_FEATURE_CONTRACT",
    "active_candidate_contract",
    "OpponentAdjustedExperimentPlan",
    "OpponentAdjustedFormContract",
    "apply_opponent_adjusted_contract",
    "load_opponent_adjusted_experiment_plan",
    "run_opponent_adjusted_experiments",
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
    "ManualMoneyline",
    "OddsInputError",
    "parse_user_odds",
    "load_moneylines",
    "moneylines_from_records",
    "build_moneyline_template",
    "write_moneyline_template",
    "collect_moneylines_interactively",
    "CapturedSlate",
    "WorkflowResult",
    "capture_official_slate",
    "evaluate_captured_slate",
    "AttributionInputError",
    "leave_group_at_reference_sensitivity",
    "FEATURE_GROUP_ORDER",
    "UnclassifiedFeatureError",
    "feature_group_for",
    "group_feature_names",
    "validate_feature_groups",
]
