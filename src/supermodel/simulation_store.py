from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np

from .market_schema import MarketQuote, MarketType
from .pricing import OutcomeProbability


SIMULATION_SNAPSHOT_SCHEMA_VERSION = 2


def _utc_iso(value: datetime | str) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SimulationSnapshot:
    game_pk: int
    away_team: str
    home_team: str
    model_track: str
    model_version: str
    git_commit: str
    input_snapshot_hash: str
    created_at: datetime | str
    random_seed: int
    away_runs: np.ndarray = field(repr=False)
    home_runs: np.ndarray = field(repr=False)
    away_win_probability: float | None = None
    home_win_probability: float | None = None
    component_probabilities: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SIMULATION_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        away = np.asarray(self.away_runs, dtype=np.int16)
        home = np.asarray(self.home_runs, dtype=np.int16)
        if int(self.game_pk) <= 0:
            raise ValueError("game_pk must be positive")
        if away.ndim != 1 or home.ndim != 1 or len(away) != len(home) or len(away) == 0:
            raise ValueError("away_runs and home_runs must be equal-length non-empty vectors")
        if np.any(away < 0) or np.any(home < 0):
            raise ValueError("simulated runs cannot be negative")
        if not str(self.away_team).strip() or not str(self.home_team).strip():
            raise ValueError("away_team and home_team are required")
        if not str(self.input_snapshot_hash).strip():
            raise ValueError("input_snapshot_hash is required")
        away_probability = self.away_win_probability
        home_probability = self.home_win_probability
        if (away_probability is None) != (home_probability is None):
            raise ValueError("away and home win probabilities must be supplied together")
        if away_probability is not None:
            away_probability = float(away_probability)
            home_probability = float(home_probability)
            if not 0.0 <= away_probability <= 1.0 or not 0.0 <= home_probability <= 1.0:
                raise ValueError("win probabilities must be between zero and one")
            if abs((away_probability + home_probability) - 1.0) > 1e-8:
                raise ValueError("away and home win probabilities must sum to one")
        object.__setattr__(self, "away_team", str(self.away_team).strip().upper())
        object.__setattr__(self, "home_team", str(self.home_team).strip().upper())
        object.__setattr__(self, "model_track", str(self.model_track).strip().lower())
        object.__setattr__(self, "created_at", _utc_iso(self.created_at))
        object.__setattr__(self, "away_runs", away)
        object.__setattr__(self, "home_runs", home)
        object.__setattr__(self, "away_win_probability", away_probability)
        object.__setattr__(self, "home_win_probability", home_probability)

    @property
    def simulations(self) -> int:
        return int(len(self.away_runs))

    @property
    def score_draws_sha256(self) -> str:
        digest = sha256()
        digest.update(self.away_runs.tobytes(order="C"))
        digest.update(self.home_runs.tobytes(order="C"))
        return digest.hexdigest()

    @property
    def snapshot_id(self) -> str:
        identity = {
            "schema_version": self.schema_version,
            "game_pk": int(self.game_pk),
            "model_track": self.model_track,
            "model_version": self.model_version,
            "git_commit": self.git_commit,
            "input_snapshot_hash": self.input_snapshot_hash,
            "created_at": self.created_at,
            "random_seed": int(self.random_seed),
            "simulations": self.simulations,
            "score_draws_sha256": self.score_draws_sha256,
            "away_win_probability": self.away_win_probability,
            "home_win_probability": self.home_win_probability,
            "score_draws_sha256": self.score_draws_sha256,
        }
        return sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def probability_for_quote(self, quote: MarketQuote) -> OutcomeProbability:
        if int(quote.game_pk) != int(self.game_pk):
            raise ValueError("quote game_pk does not match snapshot")
        away = self.away_runs
        home = self.home_runs
        market_type = MarketType(str(quote.market_type))

        if market_type is MarketType.MONEYLINE:
            if quote.selection == self.away_team:
                authoritative = self.away_win_probability
            elif quote.selection == self.home_team:
                authoritative = self.home_win_probability
            else:
                raise ValueError("moneyline selection does not match snapshot teams")
            if authoritative is not None:
                return OutcomeProbability(win=float(authoritative), push=0.0)
            ties = away == home
            if quote.selection == self.away_team:
                win_probability = float(np.mean(away > home) + 0.5 * np.mean(ties))
            else:
                win_probability = float(np.mean(home > away) + 0.5 * np.mean(ties))
            return OutcomeProbability(win=win_probability, push=0.0)
        elif market_type is MarketType.RUN_LINE:
            if quote.selection == self.away_team:
                adjusted = away.astype(float) + float(quote.line)
                opponent = home.astype(float)
            elif quote.selection == self.home_team:
                adjusted = home.astype(float) + float(quote.line)
                opponent = away.astype(float)
            else:
                raise ValueError("run-line selection does not match snapshot teams")
            wins = adjusted > opponent
            pushes = adjusted == opponent
        elif market_type is MarketType.GAME_TOTAL:
            total = away + home
            if quote.selection == "OVER":
                wins = total > float(quote.line)
                pushes = total == float(quote.line)
            else:
                wins = total < float(quote.line)
                pushes = total == float(quote.line)
        elif market_type is MarketType.TEAM_TOTAL:
            if quote.team == self.away_team:
                runs = away
            elif quote.team == self.home_team:
                runs = home
            else:
                raise ValueError("team-total team does not match snapshot teams")
            if quote.selection == "OVER":
                wins = runs > float(quote.line)
                pushes = runs == float(quote.line)
            else:
                wins = runs < float(quote.line)
                pushes = runs == float(quote.line)
        else:  # pragma: no cover - enum exhaustiveness
            raise ValueError(f"unsupported market type: {market_type}")
        return OutcomeProbability(win=float(np.mean(wins)), push=float(np.mean(pushes)))

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "game_pk": int(self.game_pk),
            "away_team": self.away_team,
            "home_team": self.home_team,
            "model_track": self.model_track,
            "model_version": self.model_version,
            "git_commit": self.git_commit,
            "input_snapshot_hash": self.input_snapshot_hash,
            "created_at": self.created_at,
            "random_seed": int(self.random_seed),
            "simulations": self.simulations,
            "away_win_probability": self.away_win_probability,
            "home_win_probability": self.home_win_probability,
            "component_probabilities": dict(self.component_probabilities),
            "metadata": dict(self.metadata),
        }


class LocalSimulationSnapshotStore:
    def __init__(self, root: str | Path = "runtime/simulations") -> None:
        self.root = Path(root)

    def _paths(self, snapshot: SimulationSnapshot) -> tuple[Path, Path]:
        directory = self.root / str(snapshot.game_pk) / snapshot.model_track
        return directory / f"{snapshot.snapshot_id}.json", directory / f"{snapshot.snapshot_id}.npz"

    def save(self, snapshot: SimulationSnapshot) -> tuple[Path, Path]:
        manifest_path, arrays_path = self._paths(snapshot)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        arrays_tmp = arrays_path.with_suffix(".npz.tmp")
        with arrays_tmp.open("wb") as handle:
            np.savez_compressed(handle, away_runs=snapshot.away_runs, home_runs=snapshot.home_runs)
        arrays_tmp.replace(arrays_path)
        manifest = snapshot.manifest()
        manifest["arrays_path"] = arrays_path.name
        manifest_tmp = manifest_path.with_suffix(".json.tmp")
        manifest_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_tmp.replace(manifest_path)
        return manifest_path, arrays_path

    def load(self, manifest_path: str | Path) -> SimulationSnapshot:
        path = Path(manifest_path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        arrays_path = path.parent / manifest["arrays_path"]
        with np.load(arrays_path) as arrays:
            away_runs = arrays["away_runs"].copy()
            home_runs = arrays["home_runs"].copy()
        return SimulationSnapshot(
            game_pk=int(manifest["game_pk"]),
            away_team=manifest["away_team"],
            home_team=manifest["home_team"],
            model_track=manifest["model_track"],
            model_version=manifest["model_version"],
            git_commit=manifest["git_commit"],
            input_snapshot_hash=manifest["input_snapshot_hash"],
            created_at=manifest["created_at"],
            random_seed=int(manifest["random_seed"]),
            away_runs=away_runs,
            home_runs=home_runs,
            away_win_probability=manifest.get("away_win_probability"),
            home_win_probability=manifest.get("home_win_probability"),
            component_probabilities=manifest.get("component_probabilities") or {},
            metadata=manifest.get("metadata") or {},
            schema_version=int(manifest.get("schema_version", 1)),
        )

    def list_latest(
        self,
        *,
        event_date: str | None = None,
        model_track: str = "production",
    ) -> list[SimulationSnapshot]:
        snapshots: list[SimulationSnapshot] = []
        for game_directory in sorted(self.root.glob("*")):
            if not game_directory.is_dir() or not game_directory.name.isdigit():
                continue
            snapshot = self.latest(int(game_directory.name), model_track=model_track)
            if snapshot is None:
                continue
            if event_date is not None and str(snapshot.metadata.get("game_date")) != str(event_date):
                continue
            snapshots.append(snapshot)
        return sorted(snapshots, key=lambda item: (item.created_at, item.game_pk))

    def latest(self, game_pk: int, *, model_track: str = "production") -> SimulationSnapshot | None:
        directory = self.root / str(int(game_pk)) / str(model_track).lower()
        manifests = sorted(directory.glob("*.json"))
        if not manifests:
            return None
        latest_path = max(
            manifests,
            key=lambda path: json.loads(path.read_text(encoding="utf-8"))["created_at"],
        )
        return self.load(latest_path)
