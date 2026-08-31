# Limitations and production path

Heimdall v2.1 is a deliberately tight, reviewer-runnable teaching artifact. Its boundaries are part
of the design, not hidden gaps.

## Real in v2

- PostgreSQL telemetry, logs, deployments, scenario tables, and service state
- pgvector runbook storage and similarity search
- real `EXPLAIN (FORMAT JSON)` and `pg_stat_*` queries
- typed read/mutate tool metadata and the uniform mutation gate
- HMAC approval tokens bound to call ID, tool, exact argument hash, and TTL
- real approved Postgres `CREATE INDEX`; modeled service changes persist in `service_state`
- append-only, fsync'd JSONL audit events
- deterministic scenario scoring with structural evidence verification
- real one-shot HTTPS, DNS, and TLS snapshots for `arjunrnair.com` and `jobs.msemail.xyz`, behind
  exact-host and resolved-IP scope checks
- real bounded discovery and crawling for `arjunrnair.com` and its label-boundary subdomains

## Live synthetics boundary

- A live report is one snapshot from one runner, not a time series, SLA, availability claim, or
  scored benchmark. Network and target state make it deliberately non-deterministic.
- The default is three sequential HTTP samples (`LIVE_PROBE_SAMPLES` may change N, from 1 to 20).
  Reported p50/p95 values describe only those successful samples; a failure is reported as a
  failure rather than converted into a fabricated metric.
- Only two exact HTTPS hosts are in scope. Redirects are manually followed only after the same
  allow-list and public-IP checks. DNS rebinding between validation and the underlying client's
  connection remains a residual risk; production should pin the validated address while retaining
  hostname verification and SNI.
- Response bodies are untrusted and discarded after local byte-count/SHA-256 derivation. They are
  not stored in tool output or supplied to the model. Cache findings use normalized values from
  two named response headers only.
- No deployment API is connected for live sites, so deployment results are honestly empty.
  Database-only tools return `not_applicable`.
- Live mode is diagnosis-only. A remediation can be proposed for human coordination, but the
  policy layer forbids execution of every mutating tool against the live datastore.

## Property crawler boundary

- `RESULTS_CRAWL.md` is a one-shot view from one runner, not an inventory guarantee, uptime
  monitor, SLA, or scored benchmark. Hosts and routes can appear or disappear between runs.
- Discovery does not use crt.sh, which was down for roughly two weeks with no ETA when CP8 was
  built. TLS SAN is primary; CertSpotter, AlienVault OTX, and Wayback are independent best-effort
  sources; a small DNS wordlist is the bounded fallback. Any source outage can reduce coverage.
- A discovered name is reported only if it passes the `arjunrnair.com` label-boundary check and
  resolves exclusively to permitted public addresses. Historical but currently unresolved names
  are omitted rather than presented as live properties.
- Crawling is sequential with at least 200 ms between same-host request starts, depth at most 2,
  at most 25 attempted pages per host, and a global cap. This is polite but not a distributed or
  geographically representative measurement.
- `robots.txt` is fetched and `Disallow` rules are honored. Sitemap and HTML links remain
  same-origin HTTPS and are scope-checked before fetch. Sites requiring JavaScript rendering,
  authentication, or non-HTML navigation are not fully mapped.
- Every route gets only a small number of sequential samples. p50/p95 therefore describe this
  snapshot, not a statistically robust latency distribution.
- Page bodies are parsed transiently for robots, sitemap locations, and links, then discarded;
  only byte counts and SHA-256 hashes survive. Remote text is never supplied to the model.
- The DNS-validation/client-connection rebinding caveat from the live probe also applies here.
  Production should connect to the validated address while retaining hostname verification/SNI.
- Property crawling remains diagnosis-only. No discovered host or route can receive a mutation.

## Intentionally modeled

- Deploy rollback, connection-pool reconfiguration, and service restart do not call Kubernetes,
  Datadog, AWS, or a deployment platform. They update seeded service state and return a
  `modeled-service-state` backend label.
- The fixture adapter mirrors versioned seed rows for fast tests and offline eval development. The
  Docker path is the production-shaped Postgres/pgvector path.
- Pending proposals are process-local in v2. A multi-worker deployment would store them in a
  transactional table and make approval consumption one-time with a unique constraint.

## Before using this at a customer

1. Replace modeled actions with customer adapters and service-account credentials scoped per tool.
2. Persist proposal state and token nonce consumption so a valid token cannot be replayed.
3. Add authentication, RBAC, tenant isolation, secret management, and audit export/retention.
4. Put the API behind a durable queue; add timeouts, retries, circuit breakers, and idempotency keys.
5. Expand schema introspection instead of using the v2 bounded database-query template.
6. Run fault-injection and frozen production regressions against each customer integration.
7. Add tracing for model tokens/latency and redact sensitive evidence before model calls.
8. Replace the one-shot probe with authenticated, durable telemetry ingestion and multiple
   controlled vantage points before drawing production reliability conclusions.

The deterministic suite proves behavior on its frozen incidents. The separate live-LLM run proves
that a configured model selected tools and produced structurally verified citations on one run; its
non-perfect tool, escalation, and grounding metrics are retained. Neither establishes reliability
on unseen incidents, replaces an SRE, or justifies autonomous remediation.
