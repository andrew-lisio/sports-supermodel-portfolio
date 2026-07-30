"""Sports SuperModel public package interface."""

from .market_schema import MarketQuote, MarketType, QuoteSource
from .pricing import (
    OutcomeProbability,
    PriceEvaluation,
    evaluate_quote,
    expected_roi,
    fair_american_odds,
    playable_through_odds,
)
from .rankings import BEST_AVAILABLE, MarketCandidate, rank_best_value, rank_high_probability
from .refresh_orchestrator import PlatformRefreshReport, refresh_platform_data
from .simulation_store import LocalSimulationSnapshotStore, SimulationSnapshot
from ._version import __version__
from .evidence import (
    EvidenceIntegrityError,
    ProspectiveEvidenceLedger,
    audit_prospective_evidence,
    write_evidence_report,
)
from .execution import (
    ExecutionPlan,
    ExecutionProfile,
    load_execution_profile,
    resolve_execution_plan,
)
from .feature_authority import (
    FEATURE_AUTHORITY_POLICY_VERSION,
    build_feature_authority_report,
    write_feature_authority_report,
)
from .pitching_context import (
    PITCHING_CONTEXT_FEATURES,
    PITCHING_CONTEXT_SCHEMA_VERSION,
    PitchingContextError,
    audit_pitching_context,
    build_pitching_context_rows,
    fetch_pitching_context,
    write_pitching_context,
)
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

from .game_registry import (
    GameRecord,
    ImmutableSnapshotStore,
    ScheduleIntegrityError,
    index_by_game_pk,
    parse_mlb_schedule,
)
from .model_registry import (
    EXPECTED_MODEL_COUNT,
    MODEL_DISPLAY_NAMES,
    MODEL_ORDER,
    MODEL_REGISTRY,
    ModelRegistration,
    ModelRegistryError,
    registry_snapshot,
    validate_runtime_models,
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
from .starter_features import (
    STARTER_SNAPSHOT_KIND,
    audit_starter_snapshots,
    export_starter_training_rows,
    latest_starter_training_rows,
    parse_innings_pitched,
    parse_pitcher_season_stats,
)
from .workflow import (
    CapturedSlate,
    WorkflowResult,
    capture_official_slate,
    evaluate_captured_slate,
)


__all__ = [
    "__version__",
    "EvidenceIntegrityError",
    "ProspectiveEvidenceLedger",
    "audit_prospective_evidence",
    "write_evidence_report",
    "ExecutionPlan",
    "ExecutionProfile",
    "load_execution_profile",
    "resolve_execution_plan",
    "EXPECTED_MODEL_COUNT",
    "MODEL_DISPLAY_NAMES",
    "MODEL_ORDER",
    "MODEL_REGISTRY",
    "ModelRegistration",
    "ModelRegistryError",
    "registry_snapshot",
    "validate_runtime_models",
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
    "FEATURE_AUTHORITY_POLICY_VERSION",
    "build_feature_authority_report",
    "write_feature_authority_report",
    "PITCHING_CONTEXT_FEATURES",
    "PITCHING_CONTEXT_SCHEMA_VERSION",
    "PitchingContextError",
    "audit_pitching_context",
    "build_pitching_context_rows",
    "fetch_pitching_context",
    "write_pitching_context",
    "AttributionInputError",
    "leave_group_at_reference_sensitivity",
    "FEATURE_GROUP_ORDER",
    "UnclassifiedFeatureError",
    "feature_group_for",
    "group_feature_names",
    "validate_feature_groups",
    "STARTER_SNAPSHOT_KIND",
    "audit_starter_snapshots",
    "export_starter_training_rows",
    "latest_starter_training_rows",
    "parse_innings_pitched",
    "parse_pitcher_season_stats",
    "MarketQuote",
    "MarketType",
    "QuoteSource",
    "OutcomeProbability",
    "PriceEvaluation",
    "evaluate_quote",
    "expected_roi",
    "fair_american_odds",
    "playable_through_odds",
    "BEST_AVAILABLE",
    "MarketCandidate",
    "rank_best_value",
    "rank_high_probability",
    "PlatformRefreshReport",
    "refresh_platform_data",
    "LocalSimulationSnapshotStore",
    "SimulationSnapshot",
]
