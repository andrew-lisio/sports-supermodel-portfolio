# Third-party data and redistribution policy

The public portfolio repository is intentionally code-first. It does not redistribute private sportsbook screenshots, private-book account metadata, historical live betting outputs, or copied third-party season datasets whose redistribution permissions have not been independently verified.

## Retrosheet

Retrosheet play-by-play data was used to build and validate the plate-appearance simulation architecture. The packaged PA prior is a derived statistical artifact rather than a copy of the raw event-file archive. Retrosheet requires prominent attribution when its data or products based on its data are redistributed. The repository owner should verify the current official notice before changing repository visibility.

## MLB Stats API and Baseball Savant / Statcast

Live and point-in-time workflows can consume public MLB endpoints and Baseball Savant / Statcast context. Raw network captures are runtime artifacts and are not required to be committed to the public portfolio repository. Users are responsible for complying with provider terms, rate limits, attribution requirements, and trademark rules.

## Historical team-log seed data

Earlier development snapshots included team CSV files copied from another public GitHub project. Because public availability does not by itself grant redistribution rights, those copied files are intentionally excluded from this portfolio snapshot. Tests rely on fixtures; a full live deployment should build or obtain historical inputs from a source whose redistribution and usage terms have been reviewed.

## Private market inputs

User-entered odds, account metadata, screenshots, balances, credit information, and generated live recommendations are local/runtime data and must not be committed. `.gitignore` blocks the standard private-output paths.
