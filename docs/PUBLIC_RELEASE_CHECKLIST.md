# Public portfolio release checklist

Use this checklist before publishing a recruiter-facing repository. The safest publication path is a **new public repository created from the cleaned snapshot**, not changing the private development repository to public, because old private files may remain reachable in Git history.

## Content and privacy

- [ ] `snapshots/private_book/` is absent.
- [ ] `reports/live/` is absent.
- [ ] `examples/historical_runs/` is absent.
- [ ] No screenshots, account balances, credit information, cookies, tokens, `.env` files, or provider credentials are present.
- [ ] Private/local runtime paths are ignored by `.gitignore`.
- [ ] Public examples contain only synthetic or intentionally shareable inputs.

## Third-party data

- [ ] `NOTICE.md` is reviewed and Retrosheet's current required attribution is displayed prominently.
- [ ] `docs/THIRD_PARTY_DATA.md` accurately describes included and excluded data.
- [ ] No copied dataset is redistributed unless permission has been verified.
- [ ] Provider terms and trademark requirements have been reviewed for any hosted/public use.

## Engineering

- [ ] `python -m compileall -q src app.py tests` passes.
- [ ] `python -m ruff check .` passes.
- [ ] `python -m pytest` passes.
- [ ] `python -m build` passes.
- [ ] Python 3.11 and 3.12 GitHub Actions jobs pass.
- [ ] README metrics match the canonical validation artifacts.
- [ ] Experimental PA output remains `production_authority=false`.

## GitHub presentation

- [ ] Use a new clean public repository with fresh history.
- [ ] Add a concise repository description and topics such as `mlb`, `machine-learning`, `sports-analytics`, `monte-carlo`, and `python`.
- [ ] Enable secret scanning / push protection where available.
- [ ] Keep the private development repository private.
- [ ] Put the clean public repository URL on the resume.

## Hosted deployment

Public source visibility is separate from public application hosting. Do not activate hosted deployment solely because the portfolio repository is public. The dormant deployment gates remain unchanged.


## Portfolio-publication gates

- [ ] Publish only from the sanitized portfolio clone, never by changing the private development repository to public.
- [ ] Confirm rewritten history contains no `Zeb1x` attribution and uses Andrew Lisio for those genuine user-authored commits.
- [ ] Confirm private/runtime paths are absent from all reachable Git objects.
- [ ] Run a history-wide secret scan after filtering and before adding any public remote.
- [ ] Insert Retrosheet's current required attribution statement in `NOTICE.md` before publication.
- [ ] Run public-repository audit, Ruff, pytest, package build, and GitHub Actions before publication.
