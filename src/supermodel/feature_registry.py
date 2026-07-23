"""Named feature groups for the V2.4 MLB feature-engine refactor.

This module deliberately does not change model inputs or model probabilities.  It
adds a single source of truth for assigning every numeric model feature to one
baseball category.  Later V2.4 work can use the same registry for attribution,
validation, diagnostics, and category-level reporting.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

FEATURE_GROUP_ORDER: tuple[str, ...] = (
    "team_strength",
    "offense",
    "run_prevention",
    "recent_form",
    "starting_pitcher",
    "bullpen",
    "lineup",
    "injuries",
    "defense",
    "baserunning",
    "rest_and_travel",
    "home_field",
    "park_and_umpire",
    "weather",
    "market",
)


class UnclassifiedFeatureError(ValueError):
    """Raised when a model feature has no V2.4 category assignment."""


def _base_name(feature_name: str) -> str:
    """Remove transport/missingness prefixes while retaining feature meaning."""

    name = feature_name
    if name.startswith("live_"):
        name = name.removeprefix("live_")
    elif name.startswith("missing_") and name != "missing_home_away":
        name = name.removeprefix("missing_")
    return name


def feature_group_for(feature_name: str) -> str:
    """Return the single baseball category assigned to ``feature_name``.

    The matching order is intentional: narrowly defined live categories are
    checked before broad rolling-stat patterns.
    """

    if feature_name in {"team_a_is_home", "missing_home_away"}:
        return "home_field"

    name = _base_name(feature_name)

    if name.startswith((
        "starter_",
        "times_through_order_penalty",
    )):
        return "starting_pitcher"

    if name.startswith(("bullpen_", "closer_available")):
        return "bullpen"

    if name.startswith((
        "lineup_",
        "platoon_edge",
    )):
        return "lineup"

    if name.startswith("injury_"):
        return "injuries"

    if name.startswith(("defense_", "catcher_framing")):
        return "defense"

    if name.startswith("baserunning_"):
        return "baserunning"

    if name.startswith((
        "travel_",
        "time_zones_crossed",
        "rest_days",
        "games_last3",
        "games_last7",
    )):
        return "rest_and_travel"

    if name.startswith(("umpire_", "park_")):
        return "park_and_umpire"

    if name.startswith((
        "weather_",
        "air_density",
        "wind_out_component",
        "rain_risk",
    )):
        return "weather"

    if name.startswith((
        "market_",
        "reverse_line_move",
    )):
        return "market"

    if name.startswith((
        "last_",
        "win5",
        "win10",
        "win20",
        "rf5",
        "rf10",
        "rf20",
        "ra5",
        "ra10",
        "ra20",
        "rd5",
        "rd10",
        "rd20",
        "ewm_",
        "form_",
    )):
        return "recent_form"

    if name.startswith("rf_pg"):
        return "offense"

    if name.startswith(("ra_pg", "run_diff_pg")):
        return "run_prevention"

    if name.startswith(("games_diff", "win_pct", "pyth")):
        return "team_strength"

    raise UnclassifiedFeatureError(
        f"Feature {feature_name!r} is not assigned to a V2.4 feature group"
    )


def group_feature_names(feature_names: Iterable[str]) -> dict[str, list[str]]:
    """Group features in stable category order without changing feature order."""

    grouped: OrderedDict[str, list[str]] = OrderedDict(
        (group_name, []) for group_name in FEATURE_GROUP_ORDER
    )
    seen: set[str] = set()

    for feature_name in feature_names:
        if feature_name in seen:
            raise ValueError(f"Duplicate model feature: {feature_name}")
        seen.add(feature_name)
        grouped[feature_group_for(feature_name)].append(feature_name)

    return {name: values for name, values in grouped.items() if values}


def validate_feature_groups(feature_names: Iterable[str]) -> None:
    """Fail closed when features are duplicated, missing, or multiply assigned."""

    names = list(feature_names)
    grouped = group_feature_names(names)
    assigned = [name for values in grouped.values() for name in values]

    if len(assigned) != len(names) or set(assigned) != set(names):
        raise ValueError("Feature-group registry does not cover the model feature set exactly once")
