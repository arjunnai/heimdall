<p align="center">
  <img src="assets/heimdall-banner.png" alt="Heimdall" width="100%">
</p>

<h1 align="center">Nothing crosses the bridge without you.</h1>

<p align="center">
  <strong>Heimdall investigates production incidents, grounds every root-cause claim in the exact evidence that proves it, and gates every state-changing action behind a human-signed approval.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-v1-2ea44f?style=flat" alt="Status">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/stack-FastAPI%20%7C%20MCP%20%7C%20pgvector-4b8bbe?style=flat" alt="Stack">
  <img src="https://img.shields.io/badge/unsafe--action-6.2%25%20%E2%86%92%200.0%25-2ea44f?style=flat" alt="Unsafe action rate">
  <img src="https://img.shields.io/badge/tests-17%20passing-2ea44f?style=flat" alt="Tests">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat" alt="License">
</p>

<p align="center">
  <a href="#why">Why</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#tools">Tools</a> ·
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
- 15 scenarios a reviewer runs in 10 minutes

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

## How it's different

Heimdall doesn't out-scale HolmesGPT, OpenSRE, or k8sgpt — it closes the gap they share:

1. **Structured evidence grounding, scored.** Each claim ties to the exact row/line that
   backs it; the eval verifies it. Incumbents emit free text or measure only a rate.
2. **One uniform approval gate** over *every* mutating tool — signed, fail-closed, audited.
3. **Legible & reproducible** — 15 scenarios you run and defend in an interview, not a
   100-step product.

The full competitive teardown (HolmesGPT · OpenSRE · k8sgpt · Aurora · IncidentFox) is in
[`PRIOR_ART.md`](PRIOR_ART.md).

## Limitations

Honest by design (see [`LIMITATIONS.md`](LIMITATIONS.md)):

- **Real:** Postgres queries, `EXPLAIN`, pg_stat_*, pgvector RAG, the policy/approval/audit
  layer, the eval harness.
- **Simulated:** cloud backends (K8s/Datadog/AWS) — seeded but genuinely queryable; mutating
  tools model the action rather than hitting a live cluster.
- Live-model grounding drops on a few DB scenarios (see the per-scenario table) — a real,
  reported limitation, not smoothed over.

## Roadmap

- [ ] Multi-tenant config (per-tenant policies + backend adapters)
- [ ] Swap a simulated backend for a real adapter (consume HolmesGPT / k8sgpt toolsets)
- [ ] Production-miss → auto-generated regression scenario loop
- [ ] Investigator / Remediator agent split

## License

MIT © 2026 Arjun R Nair
