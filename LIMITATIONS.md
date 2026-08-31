# Limitations and production path

Heimdall v1 is a deliberately tight, reviewer-runnable teaching artifact. Its boundaries are part
of the design, not hidden gaps.

## Real in v1

- PostgreSQL telemetry, logs, deployments, scenario tables, and service state
- pgvector runbook storage and similarity search
- real `EXPLAIN (FORMAT JSON)` and `pg_stat_*` queries
- typed read/mutate tool metadata and the uniform mutation gate
- HMAC approval tokens bound to call ID, tool, exact argument hash, and TTL
- real approved Postgres `CREATE INDEX`; modeled service changes persist in `service_state`
- append-only, fsync'd JSONL audit events
- deterministic scenario scoring with structural evidence verification

## Intentionally modeled

- Deploy rollback, connection-pool reconfiguration, and service restart do not call Kubernetes,
  Datadog, AWS, or a deployment platform. They update seeded service state and return a
  `modeled-service-state` backend label.
- The fixture adapter mirrors versioned seed rows for fast tests and offline eval development. The
  Docker path is the production-shaped Postgres/pgvector path.
- Pending proposals are process-local in v1. A multi-worker deployment would store them in a
  transactional table and make approval consumption one-time with a unique constraint.

## Before using this at a customer

1. Replace modeled actions with customer adapters and service-account credentials scoped per tool.
2. Persist proposal state and token nonce consumption so a valid token cannot be replayed.
3. Add authentication, RBAC, tenant isolation, secret management, and audit export/retention.
4. Put the API behind a durable queue; add timeouts, retries, circuit breakers, and idempotency keys.
5. Expand schema introspection instead of using the v1 bounded database-query template.
6. Run fault-injection and frozen production regressions against each customer integration.
7. Add tracing for model tokens/latency and redact sensitive evidence before model calls.

The deterministic suite proves behavior on its frozen incidents. The separate live-LLM run proves
that a configured model selected tools and produced structurally verified citations on one run; its
non-perfect tool, escalation, and grounding metrics are retained. Neither establishes reliability
on unseen incidents, replaces an SRE, or justifies autonomous remediation.
