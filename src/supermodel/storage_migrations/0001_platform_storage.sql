CREATE SCHEMA IF NOT EXISTS supermodel;

CREATE TABLE IF NOT EXISTS supermodel.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS supermodel.market_quote_history (
    quote_id text PRIMARY KEY,
    event_date date NOT NULL,
    game_pk bigint NOT NULL,
    sportsbook text NOT NULL,
    market_type text NOT NULL,
    selection text NOT NULL,
    line double precision,
    team text,
    american_odds integer NOT NULL,
    captured_at timestamptz NOT NULL,
    source text NOT NULL,
    provider text,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS market_quote_history_event_date_idx
    ON supermodel.market_quote_history (event_date, captured_at DESC);
CREATE INDEX IF NOT EXISTS market_quote_history_game_idx
    ON supermodel.market_quote_history (game_pk, sportsbook, captured_at DESC);


CREATE TABLE IF NOT EXISTS supermodel.provider_market_snapshots (
    provider text NOT NULL,
    event_date date NOT NULL,
    sportsbook_key text NOT NULL,
    sportsbook text NOT NULL,
    captured_at timestamptz NOT NULL,
    PRIMARY KEY (provider, event_date, sportsbook_key)
);

CREATE TABLE IF NOT EXISTS supermodel.current_market_quotes (
    provider text NOT NULL,
    event_date date NOT NULL,
    sportsbook_key text NOT NULL,
    game_pk bigint NOT NULL,
    market_type text NOT NULL,
    selection text NOT NULL,
    line_key text NOT NULL,
    team_key text NOT NULL,
    captured_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (
        provider,
        event_date,
        sportsbook_key,
        game_pk,
        market_type,
        selection,
        line_key,
        team_key
    )
);
CREATE INDEX IF NOT EXISTS current_market_quotes_event_date_idx
    ON supermodel.current_market_quotes (event_date, sportsbook_key);

CREATE TABLE IF NOT EXISTS supermodel.simulation_snapshots (
    snapshot_id text PRIMARY KEY,
    game_pk bigint NOT NULL,
    event_date date,
    model_track text NOT NULL,
    model_version text NOT NULL,
    git_commit text NOT NULL,
    input_snapshot_hash text NOT NULL,
    created_at timestamptz NOT NULL,
    simulations integer NOT NULL CHECK (simulations > 0),
    random_seed bigint NOT NULL,
    score_draws_sha256 text NOT NULL,
    score_draws_object_ref text NOT NULL,
    manifest jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS simulation_snapshots_latest_idx
    ON supermodel.simulation_snapshots (game_pk, model_track, created_at DESC);
CREATE INDEX IF NOT EXISTS simulation_snapshots_event_date_idx
    ON supermodel.simulation_snapshots (event_date, model_track, created_at DESC);

CREATE TABLE IF NOT EXISTS supermodel.platform_state (
    state_key text PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS supermodel.game_publications (
    publication_id bigserial PRIMARY KEY,
    slate_date date NOT NULL,
    game_pk bigint NOT NULL,
    model_track text NOT NULL,
    snapshot_id text REFERENCES supermodel.simulation_snapshots(snapshot_id),
    input_snapshot_hash text NOT NULL,
    published_at timestamptz NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (slate_date, game_pk, model_track, input_snapshot_hash)
);

CREATE TABLE IF NOT EXISTS supermodel.series_context_records (
    slate_date date NOT NULL,
    game_pk bigint NOT NULL,
    captured_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (slate_date, game_pk, captured_at)
);

CREATE TABLE IF NOT EXISTS supermodel.evidence_records (
    evidence_id text PRIMARY KEY,
    game_pk bigint,
    recorded_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS supermodel.freshness_records (
    freshness_key text PRIMARY KEY,
    checked_through date,
    status text NOT NULL,
    captured_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
