-- Research Agent – PostgreSQL schema
-- Kept intentionally simple for Phase 1 (single-shot queries, no sessions)

CREATE TABLE IF NOT EXISTS research_queries (
    id          SERIAL PRIMARY KEY,
    query       TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',  -- pending | complete | failed
    plan        JSONB,                                    -- ReWOO plan steps
    result      TEXT,                                     -- final synthesized answer
    error       TEXT,
    tool_calls  JSONB,                                    -- list of tool call records
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_queries_status    ON research_queries(status);
CREATE INDEX IF NOT EXISTS idx_queries_created   ON research_queries(created_at DESC);

-- Future: sessions table for multi-turn (Phase 5 extension)
-- CREATE TABLE sessions (...);