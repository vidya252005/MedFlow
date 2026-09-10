-- MedFlow durable schema. Synthetic healthcare data only.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('ADMIN', 'ANALYST', 'VIEWER')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_ref VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    ward_id VARCHAR(40),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE events (
    event_id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(100) NOT NULL,
    patient_id VARCHAR(100),
    device_id VARCHAR(100),
    resource_id VARCHAR(100),
    event_type VARCHAR(50) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    schema_version INT NOT NULL,
    payload JSONB NOT NULL,
    trace_id VARCHAR(64) NOT NULL,
    processing_status VARCHAR(40) NOT NULL DEFAULT 'RECEIVED',
    last_error TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_patient_timestamp ON events (patient_id, event_timestamp DESC);
CREATE INDEX idx_events_device_timestamp ON events (device_id, event_timestamp DESC);
CREATE INDEX idx_events_type_timestamp ON events (event_type, event_timestamp DESC);
CREATE INDEX idx_events_status ON events (processing_status);
CREATE INDEX idx_events_trace ON events (trace_id);

CREATE TABLE predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(64) NOT NULL REFERENCES events (event_id),
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    model_hash VARCHAR(64),
    label VARCHAR(100),
    score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    latency_ms DOUBLE PRECISION,
    status VARCHAR(30) NOT NULL,
    shadow BOOLEAN NOT NULL DEFAULT FALSE,
    explanation JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_predictions_event ON predictions (event_id);
CREATE INDEX idx_predictions_model ON predictions (model_name, created_at DESC);

CREATE TABLE decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(64) NOT NULL REFERENCES events (event_id),
    patient_id VARCHAR(100),
    severity VARCHAR(20) NOT NULL,
    action VARCHAR(100) NOT NULL,
    decision_score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    triggered_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_decisions_event ON decisions (event_id);
CREATE INDEX idx_decisions_patient ON decisions (patient_id, created_at DESC);

CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id VARCHAR(100),
    event_id VARCHAR(64) NOT NULL,
    decision_id UUID,
    alert_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    message TEXT NOT NULL,
    dedup_key VARCHAR(200) NOT NULL,
    explanation JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(80),
    resolved_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ
);

CREATE INDEX idx_alerts_status ON alerts (status, created_at DESC);
CREATE INDEX idx_alerts_patient ON alerts (patient_id, created_at DESC);
CREATE INDEX idx_alerts_dedup ON alerts (dedup_key, created_at DESC);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    actor VARCHAR(100),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_trace ON audit_log (trace_id);
CREATE INDEX idx_audit_created ON audit_log (created_at DESC);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    published BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbox_unpublished ON outbox_events (published, created_at);

CREATE TABLE dlq_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_topic VARCHAR(200) NOT NULL,
    event_id VARCHAR(64),
    failure_code VARCHAR(80) NOT NULL,
    error TEXT NOT NULL,
    payload JSONB,
    replayed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dlq_created ON dlq_events (created_at DESC);
CREATE INDEX idx_dlq_replayed ON dlq_events (replayed);

CREATE TABLE pipeline_metrics_snapshots (
    id BIGSERIAL PRIMARY KEY,
    events_per_min DOUBLE PRECISION,
    p95_latency_ms DOUBLE PRECISION,
    model_success_rate DOUBLE PRECISION,
    open_alerts INT,
    consumer_lag BIGINT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
