<p align="center">
  <img src="assets/heimdall-banner.png" alt="Heimdall" width="100%">
</p>

<h1 align="center">Nothing crosses the bridge without you.</h1>

<p align="center">
  <strong>Heimdall investigates production incidents, grounds every root-cause claim in the exact evidence that proves it, and gates every state-changing action behind a human-signed approval.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-v2.1-2ea44f?style=flat" alt="Status">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/stack-FastAPI%20%7C%20MCP%20%7C%20pgvector-4b8bbe?style=flat" alt="Stack">
  <img src="https://img.shields.io/badge/unsafe--action-6.2%25%20%E2%86%92%200.0%25-2ea44f?style=flat" alt="Unsafe action rate">
  <img src="https://img.shields.io/badge/tests-27%20passing-2ea44f?style=flat" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat" alt="License">
</p>

<p align="center">
  <a href="#why">Why</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#tools">Tools</a> ·
  <a href="#live-sites">Live sites</a> ·
  <a href="#crawler--property-map">Crawler</a> ·
  <a href="#evaluation">Evaluation</a> ·
  <a href="#safety">Safety</a> ·
  <a href="#how-its-different">How it's different</a> ·
  <a href="#limitations">Limitations</a> ·
  <a href="PRIOR_ART.md">Prior art</a> ·
  <a href="ARCHITECTURE.md">Architecture doc</a>
</p>

---

`Heimdall` is an MCP-powered incident-response agent for distributed-system **and**
database failures. It reads real telemetry (metrics, logs, deployments) and retrieved
runbooks, proposes an evidence-backed remediation, and **stops for human approval before
any state-changing action**.

Diagnostic tools are read-only and run autonomously. Mutating tools return a *proposal*
and physically cannot execute without a signed approval token from the policy layer.
Every conclusion carries machine-checkable evidence ids, and an evaluation harness scores
that grounding — so the agent's behavior is measured, not asserted.

```text
POST /investigate  →  root_cause: database_connection_pool_exhaustion
                      evidence:   deploy:checkout:v42, log:checkout:pool_exhausted, ...
                      action:     rollback_deployment   (gated — awaiting approval)
```

## Why

Most AI-SRE agents optimize breadth — dozens of integrations, autonomous action. The
hard parts are the ones they skip: proving the agent is *right*, and keeping a human in
control of anything destructive.

<table>
<tr>
<td width="50%">

### A typical autonomous agent

- conclusions are free text ("the logs showed…")
- grounding is never measured
- mutating actions ride a prompt suggestion
- safety fails *open* to writes it didn't flag
- 100-step loops nobody can defend line-by-line

</td>
<td width="50%">

### Heimdall

- every claim → an exact evidence id, scored
- evidence-grounding is a first-class metric
- mutating tools need an HMAC-signed token
- forbidden actions refused by code, not the model
- 16 scenarios a reviewer runs in 10 minutes

</td>
</tr>
</table>

## Architecture

```
 incident (NL) ──▶ Streamlit UI ──HTTP──▶ FastAPI ──▶ Agent loop
                   timeline · evidence     /investigate   plan→call→observe→correlate
                   Approve/Reject          /approve /audit      │ MCP
                                                                ▼
                                    ┌─────────────────────────────────┐
                                    │           MCP tool server        │
                                    │   diagnostic (auto) │ mutating   │
                                    └───────┬─────────────────┬────────┘
                     signed approval token ◀┤  Risk policy  ◀─┘  (gate)
                                            │  + append-only audit log
                                            ▼
                              Postgres  ── metrics / logs / deployments
                              pgvector  ── runbook embeddings (RAG)
```

Read-only vs mutating is a **code-level** boundary. Citations are **structural** (checked
by the scorer). Escalation is a **first-class outcome**. Full detail in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Quickstart

```bash
# 1. Boot seeded Postgres (pgvector) + API + UI
docker compose up --build          # UI → localhost:8501 · API → localhost:8000

# 2. Diagnose one incident end-to-end
curl -s -X POST localhost:8000/investigate \
  -H 'content-type: application/json' \
  -d '{"description":"Checkout p95 rose to 1.8s after v42; pool timeouts firing."}'

# 3. Reproduce the evaluation numbers
make eval            # deterministic, Postgres backend
make eval-llm        # live model over the 16 scenarios
make verify          # lint + tests + fixture eval
```

Provider is switchable: `LLM_PROVIDER=anthropic|openai` (Anthropic primary). Config lives
in `.env` — copy `.env.example`, never commit secrets.

## Live sites

Heimdall can take a one-shot synthetics snapshot of `arjunrnair.com` or
`jobs.msemail.xyz` and investigate the resulting evidence:

```bash
make demo-live                                  # arjunrnair.com, 3 samples
LIVE_TARGET=https://jobs.msemail.xyz make demo-live
```

The live adapter measures HTTP status, TTFB and total-latency p50/p95, response bytes,
redirects, DNS resolution time, and TLS days remaining. It derives cited log events for
HTTP failures, DNS failures, near-expiry TLS, high latency, and trusted cache-header
classifications. Deployment history is returned empty because no deploy API is wired.

The boundary is code-enforced:

- Only the two exact HTTPS hosts above are accepted. Every request and redirect is resolved
  and refused if any answer is private, loopback, link-local, metadata, reserved, or otherwise
  non-public.
- Remote page bytes are quarantined: only byte count and SHA-256 survive the adapter. They never
  enter the agent prompt or tool plan.
- Live investigations are diagnosis-only. The agent may return a gated proposal, but the policy
  layer refuses every mutation against a live datastore—even after approval.

Each run overwrites [`evals/RESULTS_LIVE.md`](evals/RESULTS_LIVE.md), clearly labeled as a
non-deterministic snapshot rather than a benchmark. It does not modify either scored result file.

### Live proof — `arjunrnair.com` (real, unedited snapshot)

|  |  |
|---|---|
| Target | `https://arjunrnair.com` — 3/3 HTTP 200 |
| Latency p95 | **2186 ms** (TTFB p95 2182 ms → origin/render time, not transfer) |
| DNS / TLS | 2.1 ms · 51 days remaining |
| Diagnosis | `web_latency_regression`, grounded in cited `metric:` + `log:` evidence ids |
| Remediation | proposed, **not executed** — live-target policy forbids mutation |

Heimdall found a genuine ~2.2s p95 slowdown on a real production site and traced it to
server/origin time — no mock, no fabrication. Reproduce with `make demo-live`; full report
in [`evals/RESULTS_LIVE.md`](evals/RESULTS_LIVE.md).

## Crawler / property map

`make demo-crawl` performs a bounded, diagnosis-only crawl of `arjunrnair.com` and its
real label-boundary subdomains. It discovers hosts from the apex certificate's TLS SANs,
then independently tries CertSpotter, AlienVault OTX passive DNS, and Wayback CDX behind
short timeouts. A bounded common-subdomain DNS wordlist always runs as the self-contained
fallback. Results are deduplicated and retained only after public-DNS scope validation.

```bash
make demo-crawl
CRAWL_TARGET=https://arjunrnair.com make demo-crawl
```

As of CP8, crt.sh has been unavailable for roughly two weeks with no published ETA.
Heimdall does not query or depend on it; any passive source may fail without aborting the
run. Discovery services use their own exact host allow-list and never broaden the property
scope.

The crawler honors `robots.txt` exclusions, checks `sitemap.xml`, follows same-origin HTTPS
links only, re-validates every extracted link, caps depth at 2 and pages at 25 per host, applies
a global cap, and spaces sequential requests by at least 200 ms. Page bytes remain quarantined:
only counts and SHA-256 hashes survive into the health map, never page text. The resulting
per-host/per-route map and worst-offender correlation are written to
[`evals/RESULTS_CRAWL.md`](evals/RESULTS_CRAWL.md) as an unscored one-shot snapshot.

## Tools

Diagnostic tools auto-execute. Mutating tools are approval-gated.

| Tool | Kind | Risk |
|------|------|------|
| `query_metrics` · `get_recent_deployments` · `inspect_logs` | read-only | low |
| `search_runbooks` (pgvector RAG) | read-only | low |
| `explain_query` (real `EXPLAIN (FORMAT JSON)`) | read-only | low |
| `get_table_stats` · `get_index_stats` (pg_stat_*) | read-only | low |
| `rollback_deployment` · `increase_connection_pool` | **mutating** | medium |
| `create_index` | **mutating** | medium |
| `restart_service` | **mutating** | high |
| `request_approval` (explicit escalation primitive) | control | — |

Every tool returns structured JSON plus `evidence_ids`, and appends `{tool, args, result, ts}`
to the run trace.

## Evaluation

The harness is the point. 16 seeded scenarios (infra + database), **deterministic scoring,
no LLM-as-judge**, including required adversarial cases (DROP TABLE → refuse, hallucinated
column → no fabrication, ambiguous → escalate, duplicate index → no-op).

**Live model** (`claude-sonnet-4`, fixture backend — honest, unretouched):

| Metric | Result |
|---|---:|
| Root-cause accuracy | 100.0% |
| Tool-selection accuracy | 82.3% |
| Tool precision | 92.9% |
| Escalation accuracy | 87.5% |
| Evidence grounding | 85.2% |
| Unsafe-action rate | 0.0% |

**Guardrail before/after** (deterministic, Postgres backend):

| Variant | Unsafe-action rate |
|---|---:|
| Baseline | 6.2% |
| Guarded (fail-closed) | **0.0%** |

Full tables: [`evals/RESULTS_LLM.md`](evals/RESULTS_LLM.md) · [`evals/RESULTS.md`](evals/RESULTS.md).

## Safety

- **Signed approval tokens** — HMAC over `tool_call_id + tool + args_hash` with a TTL. No
  token, no mutation.
- **Forbidden set** — `DROP TABLE`, `delete_database`, etc. refused by the policy layer even
  if the model asks. Refusal is a *passing* safety case in evals.
- **Append-only audit log** — every outcome recorded: auto, approved, rejected, refused,
  escalated.
- **Live-target guard** — exact allow-list and resolved-IP SSRF checks run before every live
  request and redirect; mutation execution fails closed for live datastores.
- **Property boundary** — the crawler accepts only `arjunrnair.com` or a real
  `*.arjunrnair.com` label suffix; look-alikes such as `arjunrnair.com.evil.com` fail closed.

## How it's different

Heimdall doesn't out-scale HolmesGPT, OpenSRE, or k8sgpt — it closes the gap they share:

1. **Structured evidence grounding, scored.** Each claim ties to the exact row/line that
   backs it; the eval verifies it. Incumbents emit free text or measure only a rate.
2. **One uniform approval gate** over *every* mutating tool — signed, fail-closed, audited.
3. **Legible & reproducible** — 16 scenarios you run and defend in an interview, not a
   100-step product.

The full competitive teardown (HolmesGPT · OpenSRE · k8sgpt · Aurora · IncidentFox) is in
[`PRIOR_ART.md`](PRIOR_ART.md).

## Limitations

Honest by design (see [`LIMITATIONS.md`](LIMITATIONS.md)):

- **Real:** Postgres queries, `EXPLAIN`, pg_stat_*, pgvector RAG, the policy/approval/audit
  layer, the eval harness, one-shot HTTPS/DNS/TLS synthetics, and the bounded property crawler.
- **Simulated:** cloud backends (K8s/Datadog/AWS) — seeded but genuinely queryable; mutating
  tools model the action rather than hitting a live cluster.
- Live-model grounding drops on a few DB scenarios (see the per-scenario table) — a real,
  reported limitation, not smoothed over.

## Roadmap

- [ ] Multi-tenant config (per-tenant policies + backend adapters)
- [x] Add a real, diagnosis-only live synthetics adapter with SSRF and content boundaries
- [x] Add resilient subdomain discovery and a bounded, robots-aware property health map
- [ ] Add authenticated telemetry/deploy adapters (consume HolmesGPT / k8sgpt toolsets)
- [ ] Production-miss → auto-generated regression scenario loop
- [ ] Investigator / Remediator agent split

## License

MIT © 2026 Arjun R Nair
