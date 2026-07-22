from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math
import pandas as pd


@dataclass
class PredictionRecord:
    timestamp: str
    game_pk: int
    model_version: str
    home_team: str
    away_team: str
    home_probability: float
    offered_home_implied: float | None = None
    closing_home_implied: float | None = None
    home_won: int | None = None
    feature_snapshot_hash: str | None = None


class FeedbackLedger:
    """Append-only prediction, closing-line and outcome ledger."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: PredictionRecord) -> None:
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(record), sort_keys=True) + '\n')

    def frame(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        return pd.DataFrame(json.loads(line) for line in self.path.read_text().splitlines() if line.strip())

    def diagnostics(self) -> dict[str, float]:
        df = self.frame()
        if df.empty:
            return {}
        complete = df.dropna(subset=['home_won'])
        out: dict[str, float] = {'predictions': float(len(df)), 'graded': float(len(complete))}
        if not complete.empty:
            p = complete.home_probability.clip(1e-6, 1-1e-6)
            y = complete.home_won.astype(float)
            out['brier'] = float(((p-y)**2).mean())
            out['log_loss'] = float(-(y*p.map(math.log)+(1-y)*(1-p).map(math.log)).mean())
            out['accuracy'] = float(((p>=0.5).astype(int)==y).mean())
        clv = df.dropna(subset=['offered_home_implied','closing_home_implied'])
        if not clv.empty:
            out['mean_probability_clv'] = float((clv.closing_home_implied-clv.offered_home_implied).mean())
            out['positive_clv_rate'] = float((clv.closing_home_implied>clv.offered_home_implied).mean())
        return out
