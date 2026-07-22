# Public release checklist

Complete this checklist before changing the GitHub repository to public.

## Legal and policy review

- [ ] Have a qualified attorney review `DISCLAIMER.md` if the project will be marketed, monetized, promoted as a betting product, or made available to a broad public audience.
- [ ] Confirm the project complies with gambling, consumer-protection, advertising, data, privacy, and software laws in the jurisdictions you target.
- [ ] Do not claim guaranteed accuracy, profit, safety, or legal compliance.
- [ ] Keep the project described as experimental research, not a sportsbook or advisory service.

## Third-party content

- [ ] Confirm the redistribution license for every dataset under `data/`.
- [ ] Confirm that public API usage complies with current provider terms and rate limits.
- [ ] Review sportsbook screenshots and remove them if redistribution is uncertain.
- [ ] Remove or redact balances, account names, IDs, device information, or other private details.
- [ ] Confirm trademark and attribution language is accurate.

## Repository hygiene

- [ ] Run `pytest`.
- [ ] Run `git status` and inspect every staged file.
- [ ] Search for secrets: `.env`, tokens, cookies, passwords, private URLs, and API keys.
- [ ] Confirm no generated local input file is staged.
- [ ] Confirm the README, license, disclaimer, and source notes are present.
- [ ] Confirm active outputs contain no bankroll or wager-sizing columns.

## GitHub settings

- [ ] Add a clear repository description.
- [ ] Enable private vulnerability reporting.
- [ ] Enable branch protection for `main`.
- [ ] Require pull requests and passing tests for major model changes.
- [ ] Create V2.4 on a separate development branch.
