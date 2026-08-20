# Historical data policy

This repository does **not** include private runtime caches or copied third-party season CSV files.

The production/development project has used point-in-time MLB game history, MLB Stats API identity data, Baseball Savant / Statcast context, and Retrosheet play-by-play data for specific validation work. Public redistribution rights are evaluated separately from the right to access or analyze a source.

Tests in this repository use controlled fixtures and do not require a private season cache. Full local/live execution requires an approved historical input directory or a separately generated runtime cache.

See `../docs/THIRD_PARTY_DATA.md` and `../NOTICE.md`.
