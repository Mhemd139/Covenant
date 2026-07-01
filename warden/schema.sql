-- Warden persistence schema. Idempotent so it can run on init and on startup.

CREATE TABLE IF NOT EXISTS tool_snapshot (
    id            BIGSERIAL PRIMARY KEY,
    tool_name     TEXT NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    input_schema  JSONB,
    output_schema JSONB,
    schema_hash   TEXT NOT NULL,
    is_baseline   BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_tool_snapshot_tool ON tool_snapshot (tool_name, captured_at DESC);

CREATE TABLE IF NOT EXISTS call_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    tool_name  TEXT,
    method     TEXT,
    request    JSONB,
    response   JSONB,
    latency_ms INTEGER,
    is_error   BOOLEAN NOT NULL DEFAULT FALSE,
    blocked    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_call_log_ts ON call_log (ts DESC);

CREATE TABLE IF NOT EXISTS drift_event (
    id          BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tool_name   TEXT NOT NULL,
    severity    TEXT NOT NULL,          -- 'breaking' | 'compatible'
    changes     JSONB NOT NULL,
    quarantined BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_drift_event_ts ON drift_event (detected_at DESC);

CREATE TABLE IF NOT EXISTS tool_status (
    tool_name TEXT PRIMARY KEY,
    status    TEXT NOT NULL DEFAULT 'ok',   -- 'ok' | 'quarantined'
    reason    TEXT,
    since     TIMESTAMPTZ NOT NULL DEFAULT now()
);
