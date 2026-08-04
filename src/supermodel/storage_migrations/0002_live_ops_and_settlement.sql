CREATE TABLE IF NOT EXISTS supermodel.live_context_records (
    game_pk bigint NOT NULL,
    slate_date date NOT NULL,
    captured_at timestamptz NOT NULL,
    overall_status text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (game_pk, captured_at)
);
CREATE INDEX IF NOT EXISTS live_context_records_slate_idx
    ON supermodel.live_context_records (slate_date, captured_at DESC);

CREATE TABLE IF NOT EXISTS supermodel.roster_transaction_records (
    transaction_id text PRIMARY KEY,
    effective_at timestamptz,
    captured_at timestamptz NOT NULL,
    team_id bigint,
    player_id bigint,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS supermodel.recommendations (
    recommendation_id text PRIMARY KEY,
    game_pk bigint NOT NULL,
    slate_date date NOT NULL,
    model_track text NOT NULL,
    model_version text NOT NULL,
    git_commit text NOT NULL,
    market_type text NOT NULL,
    selection text NOT NULL,
    line double precision,
    sportsbook text,
    american_odds integer,
    model_probability double precision NOT NULL,
    recommendation_status text NOT NULL,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS recommendations_settlement_idx
    ON supermodel.recommendations (slate_date, game_pk, created_at DESC);

CREATE TABLE IF NOT EXISTS supermodel.settlements (
    recommendation_id text PRIMARY KEY
        REFERENCES supermodel.recommendations(recommendation_id) ON DELETE CASCADE,
    settled_at timestamptz NOT NULL,
    result text NOT NULL,
    realized_roi double precision,
    closing_odds integer,
    closing_line double precision,
    closing_line_value double precision,
    final_away_runs integer,
    final_home_runs integer,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS supermodel.performance_rollups (
    rollup_key text PRIMARY KEY,
    generated_at timestamptz NOT NULL,
    sample_size integer NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS supermodel.job_runs (
    job_run_id text PRIMARY KEY,
    job_name text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL,
    git_commit text,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS job_runs_latest_idx
    ON supermodel.job_runs (job_name, started_at DESC);

CREATE TABLE IF NOT EXISTS supermodel.audit_log (
    audit_id bigserial PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    action text NOT NULL,
    resource_type text,
    resource_id text,
    payload jsonb NOT NULL
);
