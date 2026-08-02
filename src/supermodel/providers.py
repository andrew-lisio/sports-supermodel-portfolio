from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Protocol

from .game_registry import GameRecord


@dataclass
class PregameContext:
    game_date: str
    away_team: str
    home_team: str
    game_pk: int | None = None
    probable_pitchers_confirmed: bool = False
    lineups_confirmed: bool = False
    roof_status: str | None = None
    game_datetime: str | None = None
    game_number: int | None = None
    double_header: str | None = None
    status_abstract: str | None = None
    status_detailed: str | None = None
    venue_id: int | None = None
    venue_name: str | None = None
    away_team_id: int | None = None
    home_team_id: int | None = None
    away_probable_pitcher_id: int | None = None
    home_probable_pitcher_id: int | None = None
    away_probable_pitcher_name: str | None = None
    home_probable_pitcher_name: str | None = None
    away_lineup_ids: list[int] = field(default_factory=list)
    home_lineup_ids: list[int] = field(default_factory=list)
    away_lineup_names: list[str] = field(default_factory=list)
    home_lineup_names: list[str] = field(default_factory=list)
    temperature_f: float | None = None
    weather_condition: str | None = None
    wind_description: str | None = None

    # Starting pitching
    away_starter_xera: float | None = None
    home_starter_xera: float | None = None
    away_starter_fip: float | None = None
    home_starter_fip: float | None = None
    away_starter_era: float | None = None
    home_starter_era: float | None = None
    away_starter_whip: float | None = None
    home_starter_whip: float | None = None
    away_starter_innings: float | None = None
    home_starter_innings: float | None = None
    away_starter_games_started: float | None = None
    home_starter_games_started: float | None = None
    away_starter_k_rate: float | None = None
    home_starter_k_rate: float | None = None
    away_starter_bb_rate: float | None = None
    home_starter_bb_rate: float | None = None
    away_starter_k_per_9: float | None = None
    home_starter_k_per_9: float | None = None
    away_starter_bb_per_9: float | None = None
    home_starter_bb_per_9: float | None = None
    away_starter_hr_per_9: float | None = None
    home_starter_hr_per_9: float | None = None
    away_starter_hits_per_9: float | None = None
    home_starter_hits_per_9: float | None = None
    away_starter_ground_to_air: float | None = None
    home_starter_ground_to_air: float | None = None
    away_starter_stats_snapshot_path: str | None = None
    home_starter_stats_snapshot_path: str | None = None
    away_starter_stats_snapshot_sha256: str | None = None
    home_starter_stats_snapshot_sha256: str | None = None
    away_starter_xfip: float | None = None
    home_starter_xfip: float | None = None
    away_starter_siera: float | None = None
    home_starter_siera: float | None = None
    away_stuff_plus: float | None = None
    home_stuff_plus: float | None = None
    away_location_plus: float | None = None
    home_location_plus: float | None = None
    away_pitching_plus: float | None = None
    home_pitching_plus: float | None = None
    away_csw: float | None = None
    home_csw: float | None = None
    away_k_minus_bb: float | None = None
    home_k_minus_bb: float | None = None
    away_hard_hit_allowed: float | None = None
    home_hard_hit_allowed: float | None = None
    away_barrel_allowed: float | None = None
    home_barrel_allowed: float | None = None
    away_ground_ball_rate: float | None = None
    home_ground_ball_rate: float | None = None
    away_velocity_trend: float | None = None
    home_velocity_trend: float | None = None
    away_spin_trend: float | None = None
    home_spin_trend: float | None = None
    away_pitch_mix_change: float | None = None
    home_pitch_mix_change: float | None = None

    # Lineup, availability, bullpen
    away_lineup_wrc_plus: float | None = None
    home_lineup_wrc_plus: float | None = None
    away_lineup_xwoba: float | None = None
    home_lineup_xwoba: float | None = None
    away_lineup_obp: float | None = None
    home_lineup_obp: float | None = None
    away_lineup_slg: float | None = None
    home_lineup_slg: float | None = None
    away_lineup_ops: float | None = None
    home_lineup_ops: float | None = None
    away_lineup_woba_proxy: float | None = None
    home_lineup_woba_proxy: float | None = None
    away_lineup_iso: float | None = None
    home_lineup_iso: float | None = None
    away_lineup_bb_rate: float | None = None
    home_lineup_bb_rate: float | None = None
    away_lineup_k_rate: float | None = None
    home_lineup_k_rate: float | None = None
    away_lineup_stats_coverage: float | None = None
    home_lineup_stats_coverage: float | None = None
    away_platoon_edge: float | None = None
    home_platoon_edge: float | None = None
    away_injury_war: float | None = None
    home_injury_war: float | None = None
    away_bullpen_xfip: float | None = None
    home_bullpen_xfip: float | None = None
    away_bullpen_siera: float | None = None
    home_bullpen_siera: float | None = None
    away_bullpen_era_proxy: float | None = None
    home_bullpen_era_proxy: float | None = None
    away_bullpen_whip_proxy: float | None = None
    home_bullpen_whip_proxy: float | None = None
    away_bullpen_recent_pitches: float | None = None
    home_bullpen_recent_pitches: float | None = None
    away_bullpen_recent_innings: float | None = None
    home_bullpen_recent_innings: float | None = None
    away_bullpen_high_leverage_pitches_yesterday: float | None = None
    home_bullpen_high_leverage_pitches_yesterday: float | None = None
    away_bullpen_reliever_appearances_weighted: float | None = None
    home_bullpen_reliever_appearances_weighted: float | None = None
    away_bullpen_games_observed: float | None = None
    home_bullpen_games_observed: float | None = None
    away_bullpen_fatigue: float | None = None
    home_bullpen_fatigue: float | None = None
    away_closer_available: float | None = None
    home_closer_available: float | None = None

    # Environment and fielding
    umpire_run_factor: float | None = None
    umpire_k_factor: float | None = None
    park_run_factor: float | None = None
    park_hr_factor: float | None = None
    weather_run_factor: float | None = None
    air_density: float | None = None
    wind_out_component: float | None = None
    rain_risk: float | None = None
    away_travel_fatigue: float | None = None
    home_travel_fatigue: float | None = None
    away_time_zones_crossed: float | None = None
    home_time_zones_crossed: float | None = None
    away_defense_frv: float | None = None
    home_defense_frv: float | None = None
    away_defense_oaa: float | None = None
    home_defense_oaa: float | None = None
    away_defense_fielding_pct: float | None = None
    home_defense_fielding_pct: float | None = None
    away_defense_errors_per_game: float | None = None
    home_defense_errors_per_game: float | None = None
    away_catcher_framing: float | None = None
    home_catcher_framing: float | None = None
    away_baserunning_runs: float | None = None
    home_baserunning_runs: float | None = None

    # Market intelligence
    away_open_implied: float | None = None
    home_open_implied: float | None = None
    away_current_implied: float | None = None
    home_current_implied: float | None = None
    away_close_implied: float | None = None
    home_close_implied: float | None = None
    reverse_line_move: float | None = None

    # One combined immutable context snapshot containing all optional advanced inputs.
    advanced_snapshot_path: str | None = None
    advanced_snapshot_sha256: str | None = None

    provenance: dict[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        # Local filesystem paths are runtime transport details, not portable feature
        # provenance. Snapshot digests remain in the immutable context envelope.
        record.pop("away_starter_stats_snapshot_path", None)
        record.pop("home_starter_stats_snapshot_path", None)
        record.pop("advanced_snapshot_path", None)
        return record


class FeatureProvider(Protocol):
    name: str
    def enrich(self, context: PregameContext) -> PregameContext: ...


class ProviderPipeline:
    """Runs point-in-time providers and records provenance.

    Providers are deliberately independent. A failed weather feed, for example, does
    not silently erase the lineup or Statcast inputs. Missing values remain explicit.
    """
    def __init__(self, providers: list[FeatureProvider]):
        self.providers = providers

    def run(self, context: PregameContext) -> PregameContext:
        for provider in self.providers:
            context = provider.enrich(context)
            context.provenance[provider.name] = getattr(provider, "provenance_status", "loaded")
        return context


class JsonSnapshotProvider:
    """Loads a frozen point-in-time context snapshot for reproducible backtests.

    New immutable pregame envelopes are matched by ``gamePk``. The legacy
    ``date:away@home`` mapping remains readable for existing artifacts.
    """

    name = "json_snapshot"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def enrich(self, context: PregameContext) -> PregameContext:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if document.get("kind") == "mlb_pregame":
            identity = int(document["identity"])
            if context.game_pk is not None and context.game_pk != identity:
                raise ValueError(
                    f"Pregame snapshot gamePk={identity} does not match context gamePk={context.game_pk}"
                )
            context.game_pk = identity
            fields = document.get("payload", {})
        else:
            key = f"{context.game_date}:{context.away_team}@{context.home_team}"
            fields = document.get(str(context.game_pk), {}) if context.game_pk is not None else {}
            if not fields:
                fields = document.get(key, {})

        for field_name, value in fields.items():
            if hasattr(context, field_name):
                setattr(context, field_name, value)
        return context


class OfficialScheduleSnapshotProvider:
    """Enrich a pregame context from an immutable official-schedule snapshot.

    Matching by ``game_pk`` is mandatory when the snapshot contains more than one game
    with the same teams and official date. This prevents a doubleheader row from being
    assigned to the wrong game.
    """

    name = "mlb_stats_schedule_snapshot"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _records(self) -> list[GameRecord]:
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        payload = envelope.get("payload", envelope)
        records = payload.get("records", [])
        return [GameRecord(**record) for record in records]

    def enrich(self, context: PregameContext) -> PregameContext:
        records = self._records()
        match: GameRecord | None = None
        if context.game_pk is not None:
            match = next((record for record in records if record.game_pk == context.game_pk), None)
        else:
            candidates = [
                record for record in records
                if record.official_date == context.game_date
                and context.away_team in {record.away_team_name, record.away_team_abbreviation}
                and context.home_team in {record.home_team_name, record.home_team_abbreviation}
            ]
            if len(candidates) > 1:
                raise ValueError(
                    "Ambiguous schedule match: game_pk is required for a doubleheader"
                )
            match = candidates[0] if candidates else None
        if match is None:
            raise KeyError(
                f"No official schedule record for game_pk={context.game_pk} "
                f"{context.away_team}@{context.home_team} on {context.game_date}"
            )

        context.game_pk = match.game_pk
        context.game_datetime = match.game_datetime
        context.game_number = match.game_number
        context.double_header = match.double_header
        context.status_abstract = match.status_abstract
        context.status_detailed = match.status_detailed
        context.venue_id = match.venue_id
        context.venue_name = match.venue_name
        context.away_team_id = match.away_team_id
        context.home_team_id = match.home_team_id
        context.away_probable_pitcher_id = match.away_probable_pitcher_id
        context.home_probable_pitcher_id = match.home_probable_pitcher_id
        context.away_probable_pitcher_name = match.away_probable_pitcher_name
        context.home_probable_pitcher_name = match.home_probable_pitcher_name
        context.probable_pitchers_confirmed = bool(
            match.away_probable_pitcher_id and match.home_probable_pitcher_id
        )
        return context


class MLBStatsScheduleProvider(OfficialScheduleSnapshotProvider):
    """Backward-compatible name for the official schedule snapshot provider."""

    name = "mlb_stats_schedule"


class NeutralProvider:
    """Explicit placeholder until a timestamped source is connected."""

    name = "neutral"
    provenance_status = "neutral_placeholder"

    def enrich(self, context: PregameContext) -> PregameContext:
        return context


class StatcastProvider(NeutralProvider):
    name = "baseball_savant_statcast"


class LineupInjuryProvider(NeutralProvider):
    name = "lineup_injury"


class BullpenAvailabilityProvider(NeutralProvider):
    name = "bullpen_availability"


class WeatherParkProvider(NeutralProvider):
    name = "weather_park"


class UmpireProvider(NeutralProvider):
    name = "umpire"


class TravelProvider(NeutralProvider):
    name = "travel"


class MarketProvider(NeutralProvider):
    name = "market"
