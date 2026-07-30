# V2.4 RC3 Feature-Authority Audit

The live workflow captures more information than the current base models are authorized to use.
This distinction is intentional and now machine-auditable.

Run:

```bash
sports-supermodel-features audit
```

The report separates four concepts:

1. **Historically trained winner-model signal** — the feature had enough point-in-time, nonconstant historical observations to learn from.
2. **Direct score proxy** — the feature applies a transparent, bounded adjustment outside the fitted Poisson model.
3. **Prospective adaptive context** — the feature can affect only an overlay that has independently passed its chronological activation gate.
4. **Capture only** — the feature is retained for evidence and future backfilling but has no present prediction authority.

On the current repository data, all 42 advanced `live_*` fields are missing/neutral historically. Therefore none has trained winner-model authority. `weather_run_factor` and `park_run_factor` are the only direct live score-simulation proxies. Other advanced pregame context remains evidence/adaptive-only until point-in-time historical backfilling and validation are complete.

This audit prevents the UI or analysis output from implying that merely collecting a feature means it changed the probability.

## RC3 pitching backfill foundation

The repository also provides a point-in-time historical pitching-context builder:

```bash
sports-supermodel-pitching backfill --start-date 2026-03-25 --end-date 2026-07-28
sports-supermodel-pitching audit
```

It creates starter FIP/K-BB proxies and bullpen FIP/fatigue/closer-availability features using only games completed before each prediction date. All games on the same date are snapshotted before that date updates state, preventing doubleheader leakage when the original market-capture time is unknown.

The backfill is development infrastructure only at RC3 dev1. It is not activated in the frozen RC2 shadow probability until it passes matched chronological validation.
