# Public release checklist

Complete this checklist before changing the GitHub repository to public.

## Legal and policy review

- [ ] Have a qualified attorney review `DISCLAIMER.md` if the project will be marketed, monetized, promoted as a betting product, hosted for other users, or made available to a broad public audience.
- [ ] Confirm the project complies with gambling, consumer-protection, advertising, data, privacy, accessibility, and software laws in the jurisdictions you target.
- [ ] Do not claim guaranteed accuracy, profit, safety, or legal compliance.
- [ ] Keep the project described as experimental research, not a sportsbook or advisory service.
- [ ] Do not publicly host the local Streamlit development server without a production security and legal design.

## Third-party content and data

- [ ] Confirm redistribution rights for every dataset under `data/`.
- [ ] Confirm current public API usage complies with provider terms and rate limits.
- [ ] Remove sportsbook screenshots unless redistribution rights are clear.
- [ ] Review preserved market-input snapshots and reports before publication.
- [ ] Remove or redact balances, account names, IDs, device information, private URLs, or other personal details.
- [ ] Confirm trademark and attribution language is accurate.

## Repository hygiene

- [ ] Run `pytest` and confirm all tests pass.
- [ ] Run `git status` and inspect every staged file.
- [ ] Search for secrets: `.env`, API tokens, cookies, passwords, private URLs, and credentials.
- [ ] Confirm `.streamlit/secrets.toml` is not tracked.
- [ ] Confirm no generated personal odds file is staged.
- [ ] Confirm README, license, disclaimer, input documentation, and source notes are present.
- [ ] Confirm active outputs contain no bankroll, wager-size, exposure, or Kelly columns.
- [ ] Confirm the browser and CLI call the shared model workflow rather than separate model implementations.

## User experience

- [ ] Launch `sports-supermodel-ui` locally.
- [ ] Generate a CSV template from an official slate.
- [ ] Test interactive terminal input.
- [ ] Test one American-odds file and one decimal-odds file.
- [ ] Confirm a doubleheader fails without `game_pk` and succeeds with it.
- [ ] Confirm the README installation commands work in a clean environment.

## GitHub settings

- [ ] Add a clear repository description.
- [ ] Add relevant repository topics.
- [ ] Enable private vulnerability reporting.
- [ ] Enable branch protection for `main`.
- [ ] Require pull requests and passing tests for major model changes.
- [ ] Create V2.4 on a separate development branch.

## Hosted website activation

- [ ] Confirm the user has explicitly approved public deployment.
- [ ] Run `sports-supermodel-public status` and confirm the framework was intentionally enabled.
- [ ] Run `sports-supermodel-public readiness` and resolve every failure.
- [ ] Verify a checksummed runtime backup and complete a restore rehearsal.
- [ ] Confirm PostgreSQL and object storage are configured for production.
- [ ] Confirm provider credentials and quota monitoring work without exposing secrets.
- [ ] Confirm the public Compose profile or hosting service is the only activated deployment path.
- [ ] Verify `/healthz` and `/readyz` before exposing traffic.
- [ ] Test the emergency stop by disabling the public deployment gate.

The repository framework does not provision or activate these services automatically.
