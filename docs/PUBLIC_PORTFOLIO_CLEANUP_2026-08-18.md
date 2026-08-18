# Public portfolio cleanup — 2026-08-18

This public-facing HEAD was prepared from the V2.6 PA generative integration candidate for recruiter-facing review. It is intended to sit on top of a **sanitized copy of the genuine development history**, while the original development repository remains private. Historical commit dates and meaningful development progression are preserved; private/runtime paths are removed from every rewritten commit before publication.

## Removed from the public snapshot

- `snapshots/private_book/` and all other committed runtime snapshots
- `reports/live/`
- `examples/historical_runs/`
- copied/private `data/2026/` team-log seed files
- `data/mlb-2026-asplayed.csv`
- the MIT license
- root-level internal development-report clutter

## Reorganized / added

- Root historical engineering reports moved to `docs/history/`
- PA implementation report moved to `docs/validation/`
- PA candidate manifest moved to `docs/validation/artifacts/`
- README reduced from an internal handbook to a recruiter-facing technical overview
- `COPYRIGHT.md` added to make the portfolio source-available rather than open-source
- `NOTICE.md` and `docs/THIRD_PARTY_DATA.md` added
- `data/SOURCE.md` rewritten to document the code-first public data policy
- private/runtime paths hardened in `.gitignore`
- deterministic synthetic test history added so tests no longer depend on redistributed season CSVs
- `scripts/public_repo_audit.py` added and wired into GitHub Actions
- concise current `CHANGELOG.md` / `RELEASE_NOTES.md` added; detailed history archived

## Verification in the cleanup environment

- Public repository privacy audit: PASS
- `python -m compileall -q src app.py tests`: PASS
- `python -m pytest`: **211 passed**
- Relative Markdown link audit: PASS
- Heuristic scan found no AWS access key, GitHub token, OpenAI-style key, or private-key block in the cleaned snapshot

Ruff and package-build verification should still be rerun in the repository owner's Python 3.12 environment before publication because the cleanup sandbox did not have the pinned Ruff/build modules installed.

## Two publication metadata items still require owner confirmation

1. **Retrosheet notice:** the official Retrosheet notices page requires a specific prominent attribution statement. `NOTICE.md` currently describes that requirement but should be updated with the current official wording before the public repository is published.
2. **Public author identity:** finalized as Andrew Lisio using the GitHub noreply address `291412269+andrew-lisio@users.noreply.github.com`.

## Recommended publication path

Do not change the private development repository to public. Publish from the separately sanitized history clone after the history-wide path scrub, author-identity correction, public HEAD cleanup, secret scan, and full verification gates have passed. The public repository should preserve the meaningful development timeline without exposing the private repository or its unsanitized history.
