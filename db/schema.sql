-- OLTP schema: operational tables for the pipeline
-- Targets: SQLite (dev) and PostgreSQL (prod)
-- UUID fields stored as TEXT for SQLite compatibility
-- JSON payload stored as TEXT; PostgreSQL prod may ALTER to JSONB after init

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id          TEXT      PRIMARY KEY,
    started_at      TIMESTAMP NOT NULL,
    completed_at    TIMESTAMP,
    source_name     TEXT      NOT NULL,
    records_fetched INTEGER   DEFAULT 0,
    notes           TEXT
);

-- Append-only: records are never modified after insert
CREATE TABLE IF NOT EXISTS raw_jobs (
    raw_id        TEXT      PRIMARY KEY,
    run_id        TEXT      NOT NULL REFERENCES collection_runs(run_id),
    source_name   TEXT      NOT NULL,
    source_job_id TEXT,                  -- null for sources with no native ID (e.g. Careerjet)
    source_url    TEXT      NOT NULL,
    raw_payload   TEXT      NOT NULL,    -- full API response as JSON string
    collected_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_jobs_dedup
    ON raw_jobs(source_name, source_job_id);

CREATE INDEX IF NOT EXISTS idx_raw_jobs_url
    ON raw_jobs(source_url);

-- Every quality rule violation is logged here; records are never silently dropped
-- job_id is a logical reference to the Snowflake jobs table (no DB-level FK — cross-database)
CREATE TABLE IF NOT EXISTS quality_log (
    log_id    TEXT      PRIMARY KEY,
    job_id    TEXT,
    rule_name TEXT      NOT NULL,
    severity  TEXT      NOT NULL CHECK(severity IN ('info', 'warning', 'error')),
    message   TEXT      NOT NULL,
    logged_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quality_log_job
    ON quality_log(job_id);

CREATE INDEX IF NOT EXISTS idx_quality_log_rule
    ON quality_log(rule_name);

-- Tracks fingerprints of every non-duplicate record that has passed through
-- the pipeline. Used for cross-run deduplication when a source (e.g. Careerjet)
-- has no native source_job_id. Populated by deduplicator.py after each run.
-- Fingerprints from sources with native IDs are recorded here too, enabling
-- uniform cross-source dedup via Stage 3 when a second source is added.
CREATE TABLE IF NOT EXISTS processed_fingerprints (
    fingerprint  TEXT      PRIMARY KEY,
    first_raw_id TEXT      NOT NULL,
    source_name  TEXT      NOT NULL,
    recorded_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_processed_fp_source
    ON processed_fingerprints(source_name);
