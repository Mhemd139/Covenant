-- Covenant Layer 2 store. Idempotent: safe to run on every connect.

CREATE TABLE IF NOT EXISTS tool_status (
    tool   TEXT PRIMARY KEY,
    status TEXT NOT NULL,              -- 'quarantined' (the only status Covenant writes)
    reason TEXT,
    since  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drift_events (
    id       BIGSERIAL PRIMARY KEY,
    tool     TEXT NOT NULL,
    severity TEXT NOT NULL,            -- 'breaking' | 'degraded'
    changes  JSONB NOT NULL,
    at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS calls (
    id         BIGSERIAL PRIMARY KEY,
    tool       TEXT,
    method     TEXT,
    latency_ms INTEGER,
    is_error   BOOLEAN NOT NULL DEFAULT false,
    blocked    BOOLEAN NOT NULL DEFAULT false,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS calls_at_idx ON calls (at DESC, id DESC);
CREATE INDEX IF NOT EXISTS drift_at_idx ON drift_events (at DESC, id DESC);
