# V1 Snapshot

This commit freezes the model state immediately before the V2 upgrade request.

V1 was a chat-resident MLB framework rather than a fully persisted training pipeline. Its documented components were:

1. Season/team-strength Log5-style estimate
2. Pythagorean/run-differential strength
3. Starting-pitcher regression proxy
4. Elo-style team strength
5. Logistic blend
6. Poisson scoring estimate
7. Bayesian/robust consensus
8. At least 10,000 Monte Carlo trials per game

The exact historical V1 picks are preserved in `reports/v1_chat_predictions.csv`. They are copied from the prior chat responses and are not regenerated.
