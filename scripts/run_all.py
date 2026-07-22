from pathlib import Path
import json
import pandas as pd

from supermodel.mlb_v2 import (
    load_team_logs, reconstruct_games, build_pregame_features,
    walk_forward_trials, replay_dates, metric_row,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / '2026'
REPORTS = ROOT / 'reports'
REPORTS.mkdir(exist_ok=True)

logs = load_team_logs(DATA)
games = reconstruct_games(logs)
features = build_pregame_features(games)

# The source logs do not preserve game IDs for doubleheaders. Exclude the affected
# date/pairs rather than pretending a collapsed row is a specific game.
excluded = {
    ('2026-07-17', 'BOS', 'TB'),
    ('2026-07-18', 'CLE', 'PIT'),
    ('2026-07-19', 'LAD', 'NYY'),
}

oof, folds = walk_forward_trials(features[features.date <= pd.Timestamp('2026-07-16')])
folds.to_csv(REPORTS/'walk_forward_folds.csv', index=False)
oof.to_csv(REPORTS/'walk_forward_predictions.csv', index=False)
summary = {
    'v1': metric_row(oof.a_win, oof.v1_probability.to_numpy()),
    'v2': metric_row(oof.a_win, oof.v2_probability.to_numpy()),
}
(REPORTS/'walk_forward_summary.json').write_text(json.dumps(summary, indent=2))

replay = replay_dates(features, ['2026-07-17','2026-07-18','2026-07-19'], 100_000, excluded)
replay.to_csv(REPORTS/'v2_retrosim_2026-07-17_to_2026-07-19.csv', index=False)
print(json.dumps(summary, indent=2))
print(replay.groupby('date').correct.agg(['sum','count','mean']))
