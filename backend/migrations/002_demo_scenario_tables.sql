-- Migration: Demo scenario tables for repeatable ingestion.
-- Run after schema_pg.sql.

-- Tracks generation state for each allowlisted demo scenario.
CREATE TABLE IF NOT EXISTS DemoScenarioState (
    scenario_key        TEXT PRIMARY KEY,
    crime_no            TEXT NOT NULL,
    generation          INTEGER NOT NULL DEFAULT 0,
    lifecycle_state     TEXT NOT NULL DEFAULT 'IDLE'
                        CHECK (lifecycle_state IN ('IDLE', 'RESETTING', 'RESET_FAILED', 'READY', 'UPLOADING', 'PROCESSING')),
    active_run_id       TEXT,
    active_operation_id UUID,
    error_message       TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable cleanup operations for each reset.
CREATE TABLE IF NOT EXISTS DemoResetOperation (
    operation_id        UUID PRIMARY KEY,
    scenario_key        TEXT NOT NULL REFERENCES DemoScenarioState(scenario_key),
    idempotency_key     TEXT NOT NULL,
    generation          INTEGER NOT NULL,
    cleanup_plan        JSONB NOT NULL DEFAULT '{}'::jsonb,
    pinecone_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (pinecone_status IN ('PENDING', 'DONE', 'SKIPPED', 'FAILED')),
    pinecone_deleted    INTEGER NOT NULL DEFAULT 0,
    neo4j_status        TEXT NOT NULL DEFAULT 'PENDING' CHECK (neo4j_status IN ('PENDING', 'DONE', 'SKIPPED', 'FAILED')),
    neo4j_deleted       INTEGER NOT NULL DEFAULT 0,
    stratus_status      TEXT NOT NULL DEFAULT 'PENDING' CHECK (stratus_status IN ('PENDING', 'DONE', 'SKIPPED', 'FAILED')),
    stratus_deleted     INTEGER NOT NULL DEFAULT 0,
    postgres_status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (postgres_status IN ('PENDING', 'DONE', 'SKIPPED', 'FAILED')),
    postgres_deleted    INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_resetop_idempotency ON DemoResetOperation(scenario_key, idempotency_key);

-- Artifact provenance: tracks what each run created in each store.
CREATE TABLE IF NOT EXISTS IngestArtifact (
    artifact_id         BIGSERIAL PRIMARY KEY,
    run_id              TEXT NOT NULL,
    case_id             INTEGER,
    scenario_key        TEXT,
    scenario_generation INTEGER,
    store               TEXT NOT NULL CHECK (store IN ('postgres', 'neo4j', 'pinecone', 'stratus')),
    artifact_type       TEXT NOT NULL,
    artifact_key        TEXT NOT NULL,
    sql_table           TEXT,
    sql_pk              TEXT,
    entity_uid          UUID,
    is_owner            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifact_run ON IngestArtifact(run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_scenario ON IngestArtifact(scenario_key, scenario_generation);
CREATE INDEX IF NOT EXISTS idx_artifact_key ON IngestArtifact(store, artifact_key);

-- Idempotent file loading: prevents Phase B from inserting the same file twice.
CREATE TABLE IF NOT EXISTS IngestFileLoad (
    run_id              TEXT NOT NULL,
    file_key            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'LOADING', 'DONE', 'FAILED')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    PRIMARY KEY (run_id, file_key)
);

-- Add scenario columns to BatchUpload and PipelineRun.
ALTER TABLE BatchUpload ADD COLUMN IF NOT EXISTS scenario_key TEXT;
ALTER TABLE BatchUpload ADD COLUMN IF NOT EXISTS scenario_generation INTEGER;

ALTER TABLE PipelineRun ADD COLUMN IF NOT EXISTS scenario_key TEXT;
ALTER TABLE PipelineRun ADD COLUMN IF NOT EXISTS scenario_generation INTEGER;

-- Uniqueness guard for duplicate review candidates within one run.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reviewqueue_run_entity_candidate
    ON ReviewQueueItem(source_run_id, entity_type, matched_against_entity_uid, (candidate_record_json::text))
    WHERE status = 'pending';
