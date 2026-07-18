-- Migration: Assistant chat persistence.
-- Run after schema_pg.sql and 002_demo_scenario_tables.sql.
--
-- Postgres holds the structured record of a conversation; Stratus holds the blobs
-- (artifact bodies, run event logs) under the assistant/ prefix. The split matters for
-- history replay: rendering a past turn needs the steps/citations and the artifact
-- *metadata* (to draw the chips), but not the artifact bodies -- those are fetched only
-- when the officer opens one.

CREATE TABLE IF NOT EXISTS AssistantSession (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT,
    case_id     BIGINT,           -- the case in context when the session started, if any
    language    TEXT NOT NULL DEFAULT 'en',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assistant_session_user ON AssistantSession(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS AssistantMessage (
    message_id  BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES AssistantSession(session_id) ON DELETE CASCADE,
    run_id      TEXT,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL DEFAULT '',
    -- steps / citations / actions / artifact metadata for this turn, so a replayed
    -- conversation renders its reasoning trail without re-running anything.
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assistant_message_session ON AssistantMessage(session_id, message_id);

-- Cross-session memory about an officer: jurisdiction, speciality, answer preferences.
-- Kept per user_id and never shared between officers.
CREATE TABLE IF NOT EXISTS AssistantUserMemory (
    memory_id     BIGSERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'preference',
    content       TEXT NOT NULL,
    source_run_id TEXT,
    -- Deactivated rather than deleted: a superseded memory is still an audit trail of
    -- what the assistant believed when it answered an earlier turn.
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assistant_memory_user ON AssistantUserMemory(user_id) WHERE active;

-- Artifacts produced by a run. Body lives in Stratus; this row is what the artifact
-- endpoint resolves an id against, and what history replay reads to draw chips.
CREATE TABLE IF NOT EXISTS AssistantArtifact (
    artifact_id TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES AssistantSession(session_id) ON DELETE CASCADE,
    run_id      TEXT,
    kind        TEXT NOT NULL,
    title       TEXT,
    stratus_key TEXT,
    -- Small artifacts (tables, graphs) are kept inline: fetching a few KB from Stratus
    -- to redraw a chip the officer already saw is a round-trip for nothing.
    body        JSONB,
    -- Rendered PDF bytes. Stratus is the durable copy, but a report the officer is about
    -- to attach to a case file should not become undownloadable because object storage
    -- had a bad minute -- the artifact endpoint serves this when Stratus misses.
    blob        BYTEA,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assistant_artifact_run ON AssistantArtifact(run_id);
