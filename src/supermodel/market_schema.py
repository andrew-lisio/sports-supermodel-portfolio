from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from typing import Any


class MarketType(StrEnum):
    MONEYLINE = "moneyline"
    RUN_LINE = "run_line"
    GAME_TOTAL = "game_total"
    TEAM_TOTAL = "team_total"


class QuoteSource(StrEnum):
    PROVIDER = "provider"
    MANUAL = "manual"
    CONSENSUS = "consensus"


def _utc_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketQuote:
    """Canonical price for one sportsbook outcome.

    ``selection`` is the team abbreviation for moneylines/run lines and ``OVER`` or
    ``UNDER`` for totals. Team totals additionally require ``team``.
    """

    game_pk: int
    sportsbook: str
    market_type: MarketType | str
    selection: str
    american_odds: int
    captured_at: datetime | str
    line: float | None = None
    team: str | None = None
    provider_updated_at: datetime | str | None = None
    source: QuoteSource | str = QuoteSource.PROVIDER
    event_date: str | None = None
    provider: str | None = None
    provider_event_id: str | None = None
    provider_bookmaker_key: str | None = None
    provider_market_key: str | None = None

    def __post_init__(self) -> None:
        market_type = MarketType(str(self.market_type))
        source = QuoteSource(str(self.source))
        sportsbook = str(self.sportsbook).strip()
        selection = str(self.selection).strip().upper()
        team = str(self.team).strip().upper() if self.team else None
        if int(self.game_pk) <= 0:
            raise ValueError("game_pk must be positive")
        if not sportsbook:
            raise ValueError("sportsbook is required")
        if not selection:
            raise ValueError("selection is required")
        odds = int(self.american_odds)
        if odds == 0 or abs(odds) < 100:
            raise ValueError("American odds must be +100 or greater, or -100 or lower")
        line = self.line
        if market_type is MarketType.MONEYLINE:
            if line is not None:
                raise ValueError("moneyline quotes cannot include a line")
            if team is not None and team != selection:
                raise ValueError("moneyline team must match selection")
        elif market_type is MarketType.RUN_LINE:
            if line is None or not math.isfinite(float(line)):
                raise ValueError("run-line quotes require a finite line")
            if selection in {"OVER", "UNDER"}:
                raise ValueError("run-line selection must be a team")
        elif market_type is MarketType.GAME_TOTAL:
            if line is None or not math.isfinite(float(line)):
                raise ValueError("game-total quotes require a finite line")
            if selection not in {"OVER", "UNDER"}:
                raise ValueError("game-total selection must be OVER or UNDER")
            if team is not None:
                raise ValueError("game totals cannot include a team")
        elif market_type is MarketType.TEAM_TOTAL:
            if line is None or not math.isfinite(float(line)):
                raise ValueError("team-total quotes require a finite line")
            if selection not in {"OVER", "UNDER"}:
                raise ValueError("team-total selection must be OVER or UNDER")
            if not team:
                raise ValueError("team-total quotes require a team")

        object.__setattr__(self, "market_type", market_type)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "sportsbook", sportsbook)
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "team", team)
        object.__setattr__(self, "american_odds", odds)
        object.__setattr__(self, "line", float(line) if line is not None else None)
        object.__setattr__(self, "captured_at", _utc_iso(self.captured_at))
        object.__setattr__(
            self, "provider_updated_at", _utc_iso(self.provider_updated_at)
        )

    @property
    def market_key(self) -> tuple[int, str, str, float | None, str | None]:
        return (
            int(self.game_pk),
            str(self.market_type),
            self.selection,
            self.line,
            self.team,
        )

    @property
    def quote_key(self) -> tuple[int, str, str, str, float | None, str | None]:
        return (
            int(self.game_pk),
            self.sportsbook.casefold(),
            str(self.market_type),
            self.selection,
            self.line,
            self.team,
        )

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["market_type"] = str(self.market_type)
        payload["source"] = str(self.source)
        return payload

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "MarketQuote":
        return cls(**record)
