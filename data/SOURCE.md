# Historical game-log source

The 2026 team CSV files were downloaded on 2026-07-20 from the public `fantasy-toolz/mlb-predictions` GitHub repository (`data/2026/teams`). The upstream project states that its outcomes are scraped and processed from MLB and Baseball Savant.

These files do not contain official game identifiers or home/away flags. They are adequate for a prototype team-state replay, but ambiguous doubleheader matchups are excluded. Live and future production runs should preserve official MLB `gamePk` identifiers in timestamped snapshots.

Before publishing or redistributing a repository containing third-party datasets or screenshots, the repository owner should independently confirm the applicable license, attribution requirements, API terms, trademark rules, and redistribution permissions. Inclusion here is not a representation that every third-party artifact may be republished in every jurisdiction or context.
