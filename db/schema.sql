CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS metrics (
    evidence_id text PRIMARY KEY,
    service text NOT NULL,
    metric text NOT NULL,
    value double precision NOT NULL,
    unit text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS metrics_service_metric_time
    ON metrics (service, metric, recorded_at DESC);

CREATE TABLE IF NOT EXISTS deployments (
    evidence_id text PRIMARY KEY,
    service text NOT NULL,
    version text NOT NULL,
    commit_sha text NOT NULL,
    status text NOT NULL,
    deployed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS logs (
    evidence_id text PRIMARY KEY,
    service text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS logs_service_time ON logs (service, recorded_at DESC);

CREATE TABLE IF NOT EXISTS runbook_chunks (
    evidence_id text PRIMARY KEY,
    source text NOT NULL,
    heading text NOT NULL,
    content text NOT NULL,
    embedding vector(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS runbook_chunks_embedding
    ON runbook_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS service_state (
    service text PRIMARY KEY,
    version text,
    connection_pool_size integer NOT NULL DEFAULT 20,
    restart_count integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Scenario tables make database incidents observable through real EXPLAIN/pg_stat_*.
CREATE TABLE IF NOT EXISTS orders (
    id bigserial PRIMARY KEY,
    customer_id bigint NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    notes text NOT NULL DEFAULT ''
);

