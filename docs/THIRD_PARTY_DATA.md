# Third-party data and redistribution policy

This repository does not redistribute private sportsbook screenshots, account metadata, historical private-market outputs, or copied third-party season datasets whose redistribution permissions have not been independently verified.

## Retrosheet

Retrosheet play-by-play data was used to build and validate the plate-appearance simulation architecture. The packaged PA prior is a derived statistical artifact rather than a copy of the raw event-file archive. Retrosheet requires prominent attribution when its data or products based on its data are redistributed.

## MLB Stats API and Baseball Savant / Statcast

Live and point-in-time workflows can consume public MLB endpoints and Baseball Savant / Statcast context. Raw network captures are runtime artifacts and are not required to be committed to this repository. Users are responsible for complying with provider terms, rate limits, attribution requirements, and trademark rules.

## Historical team-log seed data

Third-party team CSV files are not redistributed unless their license or permissions clearly allow it. Tests rely on fixtures; a full live deployment should build or obtain historical inputs from sources whose redistribution and usage terms have been reviewed.

## Private market inputs

User-entered odds, account metadata, screenshots, balances, credit information, and generated live recommendations are local/runtime data and must not be committed. `.gitignore` blocks the standard private-output paths.
