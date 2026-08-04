# V2.5 Accelerated Platform Integration

This branch consolidates the planned Post8–Post15 platform work into one cumulative,
reviewable branch. Each major unit remains a separate Git commit so it can be audited or
reverted independently.

## Included

1. **Fail-closed live context**
   - Official starters, batting orders, active rosters, recent transactions, weather,
     and venue roof metadata are captured with timestamps and explicit statuses.
   - Critical unresolved inputs can block recommendation eligibility without changing
     V2.3.3 or V2.4 probabilities.

2. **Shadow totals candidate**
   - Correlated overdispersed score draws, expected starter innings, push-aware total and
     team-total frontiers, and calibration/holdout utilities.
   - The candidate is marked `SHADOW_ONLY_NOT_PROMOTED`; existing production moneyline
     probabilities are not changed.

3. **Shared storage activation**
   - A second database migration for live context, recommendations, settlements,
     performance rollups, jobs, and audit events.
   - Idempotent runtime artifact upload, verification, and compressed backup commands.

4. **Separated services**
   - Read-only API, web, publisher, odds, and settlement service entry points.
   - Health/readiness endpoints and job-run records.

5. **Settlement and performance**
   - Production/shadow accuracy, Brier, log loss, ROI, CLV, and disagreement reporting
     from the prospective evidence ledger.

6. **Candidate validation gates**
   - Paired accuracy bootstrap intervals, Brier/log-loss/AUC/ECE gates, probability-change
     checks, and chronological folds.
   - Retrospective results can qualify a candidate for shadow evaluation only. They never
     auto-promote it to production.

7. **Public product completion**
   - Existing Today’s Slate, High Probability, Best Value, and Line Checker pages remain.
   - Game Analysis and Model Performance pages are added.

8. **Launch hardening**
   - Secret redaction, structured logs, rate limiting, security headers, readiness audits,
     backups, and a multi-service deployment template.

## External acceptance still required

The code does not claim that external infrastructure has been provisioned. Public launch
still requires real PostgreSQL and object-storage instances, approved provider credentials,
secret configuration, provider license review, and an end-to-end deployment test.

V2.3.3 remains the production prediction model. V2.4 RC2 remains the shadow model. The
new totals candidate and future winner candidates remain non-authoritative until their
respective validation and prospective gates pass.
