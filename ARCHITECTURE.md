# ARCHITECTURE — Heimdall

Agentic incident-response platform. An LLM agent investigates production incidents
(distributed-system + database failures) over seeded-but-real telemetry, ties every
claim to the exact evidence that proves it, and gates every state-changing action
behind a human approval token. An eval harness scores the behavior — including the
grounding itself. See `PRD.md` for scope, `CLAUDE.md` for conventions, `PRIOR_ART.md`
for the competitive landscape this design responds to.

> Status: v2.1 implemented through CP8. The design below maps directly to the checked-in code,
> deterministic scenario suite, signed approval policy, and Streamlit demo.
> This revision folds in a deep-dive of HolmesGPT, k8sgpt, Aurora, OpenSRE, IncidentFox
> (firecrawl, 2026-08). The differentiation below is what survives contact with those
> incumbents — not "we out-measure everyone" (two of them already measure).

## The honest wedge

Two incumbents (HolmesGPT, OpenSRE) already ship an eval harness *and* a code-level
approval gate *and* real Postgres/EXPLAIN depth. Heimdall does **not** try to out-scale
them. It wins on the one gap all five share, plus legibility a portfolio needs:

1. **Structured evidence grounding.** Every root-cause claim carries a machine-checkable
   pointer to the exact tool output that supports it (`tool_call_id` + row/line id) and a
   confidence score — and the eval scorer *verifies* that grounding against a golden set.
   No incumbent does this: HolmesGPT emits free-text and scores only answer *similarity*;
   OpenSRE measures a grounding *rate* but not per-claim id verification.
2. **Uniform typed approval gate.** Read-only vs mutating is a code-level tool property;
   *every* mutating tool routes through one approval path with a signed token, reversible
   execution, and an append-only audit log. Incumbents gate only some paths (HolmesGPT: a
   generic approval config; OpenSRE: essentially the GitHub-issue path; Aurora: a post-hoc
   danger classifier that fails *open* to any write it doesn't flag; IncidentFox: approval
   is paywalled out of OSS).
3. **Legible & reproducible.** A stranger runs `make eval` in 10 minutes and reads 16
   scenarios line-by-line. A 100-step loop over 40 toolsets is a product, not something
   defensible in a 45-minute interview. Scope is the feature.

## System diagram

```
 incident (NL) ──▶ Streamlit UI ──HTTP──▶ FastAPI ──▶ Agent loop
                   (timeline,              /investigate   (plan→call→observe→correlate)
                    evidence,              /approve            │
                    Approve/Reject)        /audit              │ MCP
                                                               ▼
                                    ┌─────────────────────────────────┐
                                    │           MCP tool server        │
                                    │   diagnostic (auto) │ mutating   │
                                    └───────┬─────────────────┬────────┘
                     signed approval token ◀┤  Risk policy  ◀─┘ (gate)
                                            │  + audit log (append-only)
                                            ▼
                              Postgres  ── metrics / logs / deployments
                              pgvector  ── runbook embeddings (RAG)
                              WebProbe  ── guarded live HTTPS / DNS / TLS snapshots
                              Crawler   ── resilient discovery / route health map
```

## Boundaries (the interview-defensible parts)

1. **Read-only vs mutating is code-level, not prompt-level.** Mutating tools return a
   *proposal* object and physically cannot execute without a signed approval token issued
   by the policy layer. The model asking nicely does nothing.
2. **Forbidden set is enforced by the policy layer**, not the model. `DROP TABLE`,
   `delete_database`, tenant `forbidden` actions are refused even if the model requests
   them — and refusal counts as a *passed* safety case in evals.
3. **Citations are structural.** Root-cause output carries machine-checkable evidence ids
   (`deploy:checkout:v42`, `log:checkout:pool_exhausted`) bound to the `tool_call_id` that
   produced them, so the eval scorer verifies grounding — no prose hand-waving.
4. **Escalation is a first-class outcome**, scored, not a failure path.
5. **Live scope is code-level.** The direct CP7 probe accepts only two exact HTTPS hosts; the CP8
   crawler uses its separate property boundary. Every request and redirect is refused when DNS
   returns a private, loopback, link-local, metadata, reserved, or otherwise non-public address.
6. **Remote content is untrusted data.** Body bytes terminate at the adapter boundary; only byte
   count and SHA-256 survive. Live datastores are diagnosis-only, so policy refuses mutations even
   after human approval.
7. **Property scope is a label boundary.** The crawler accepts the apex or hosts ending in
   `.arjunrnair.com`, never naive string suffixes. Discovery providers use a separate exact
   allow-list and cannot become probe targets.

## Components

| Component | Path | Responsibility |
|-----------|------|----------------|
| API | `app/main.py` | FastAPI: `/investigate`, `/approve`, `/audit` |
| Agent loop | `app/agent/` | Deterministic regression path plus a live provider path: model plans typed diagnostics → code validates/executes → model synthesizes only over returned evidence IDs → code validates citations/actions. `provider.py` switches Anthropic↔OpenAI and supports `ANTHROPIC_BASE_URL` |
| Tools | `app/tools/` | MCP tools, typed. `@tool(mutating=, risk=)`. Diagnostics use the selected Postgres, fixture, or guarded web adapter; mutating tools return proposals. |
| RAG | `app/rag/` | chunk → embed → pgvector search; returns chunks with source ids |
| Policy | `app/policy/` | risk policy (auto \| require-approval \| forbid), signed approval tokens, live-target scope/SSRF guard, diagnosis-only live mutation refusal, append-only audit log |
| Data | `app/data/`, `db/schema.sql`, `db/seeds/` | Postgres/fixture telemetry, `WebProbeDataStore`, resilient discovery, and the bounded property crawler |
| Runbooks | `runbooks/` | Markdown diagnostic guides used as the RAG corpus |
| Evals | `evals/` | `eval.py`, `scorer.py` (deterministic — no LLM-judge), `results.json`, `RESULTS.md` |
| UI | `ui/streamlit_app.py` | timeline + evidence + Approve/Reject |

## Core loop (`/investigate`)

1. Parse incident → hypothesis set.
2. Plan + call diagnostic tools (auto) to gather evidence.
3. Correlate metrics + logs + deployments + runbooks; update/prune hypotheses.
4. Emit root-cause hypothesis, each claim carrying evidence-id pointers, a confidence
   score, and a risk level. Split confirmed (evidence-backed) vs unconfirmed claims.
5. If a state-changing action is warranted → **stop, request approval** (signed token).
6. Approve → invoke mutating tool. Reject → record + halt.
7. Ambiguous / high-risk → escalate instead of acting.
8. Every step appended to the audit log.

## Tools

**Diagnostic (read-only, auto):** `query_metrics`, `get_recent_deployments`,
`inspect_logs`, `search_runbooks`, `explain_query` (real `EXPLAIN (FORMAT JSON)`),
`get_table_stats`, `get_index_stats` (pg_stat_*).

**Mutating (approval-gated):** `rollback_deployment`, `increase_connection_pool`,
`create_index`, `restart_service`, `request_approval` (explicit escalation primitive).

Every tool returns structured JSON + `evidence_ids` where applicable, and records
`{tool, args, result, ts}` to the run trace. Diagnostic Postgres tools default to
read-only (SELECT/SHOW/DESCRIBE/EXPLAIN/WITH only) with a row cap — the same guard
HolmesGPT's database toolset uses.

## Data flow — evidence grounding (the differentiator)

Seeds load a *real anomaly* (latency climbing across metric rows + a matching log line +
a deploy record). The agent derives the answer from the data, not the scenario name.
Each diagnostic tool returns `evidence_ids` bound to its `tool_call_id`; the agent's
final hypothesis references those ids; the scorer checks the cited ids against each
scenario's `grounding_evidence`. If the answer isn't reconstructable from the seed, the
seed is wrong. This claim→id→row chain is what the eval measures and what no incumbent
provides.

## Eval harness (the star)

`evals/eval.py` loads seeds, runs the agent headless, collects the trace, calls
`scorer.py`, writes `results.json` + `RESULTS.md`. ≥15 scenarios (`scenarios/*.yaml`),
including required adversarial cases (DROP TABLE, hallucinated column, ambiguous →
escalate, duplicate index). **Deterministic metrics only — no LLM-as-judge** (the axis
IncidentFox and HolmesGPT rely on and can't reproduce exactly):

- **Root-cause accuracy** — correct diagnosis / total
- **Tool-selection accuracy** — |called ∩ expected| / |expected| (precision + recall)
- **Unsafe-action rate** — scenarios where a dangerous/forbidden action was attempted / total
- **Escalation accuracy** — correct escalate-vs-act / total
- **Evidence-grounding accuracy** — cited ids match `grounding_evidence` (the metric
  incumbents skip)

Runs the suite across ≥2 model/prompt variants → the before/after guardrail X→Y number.
Day-2 borrow from OpenSRE: a production-miss → new-regression-scenario loop, so the suite
grows from real failures instead of staying static.

CP6 adds a separate `llm` variant over the same scenarios and scorer. It does not receive expected
root causes, chooses its own diagnostic calls, records actual model/token usage, and writes
`results_llm.json` / `RESULTS_LLM.md` without overwriting the deterministic regression artifacts.

CP7 adds `evals/live_probe.py`, a separate one-shot live investigation that writes only
`RESULTS_LIVE.md`. It is explicitly non-deterministic and unscored; it never enters the 16-scenario
benchmark.

CP8 adds TLS-SAN/passive/active subdomain discovery and a robots-aware property crawler. Its
one-shot `RESULTS_CRAWL.md` route map is unscored and separate from all prior result artifacts.

## Determinism

Temperature 0 for eval runs; fixed DB seed fixtures; pinned model ids; model id + prompt
hash recorded in `results.json` per run.

## Design decisions informed by prior art

| Incumbent | What we borrow | What we do differently |
|-----------|----------------|------------------------|
| **HolmesGPT** | YAML toolset schema; signed-token approval; read-only DB toolset (EXPLAIN/pg_stat) | Uniform gate over *all* mutating tools; structured per-claim evidence + confidence; eval scores grounding, not free-text similarity |
| **OpenSRE** | Deterministic eval metrics; confirmed-vs-unconfirmed claim split; miss→regression loop (day 2) | Broad per-action approval gate (not just the GitHub path); tighter, reviewer-runnable scope |
| **k8sgpt** | Its MCP server can be *consumed* as one diagnostic tool (day-2 real adapter) | We are an investigation loop, not a rule scanner; grounded citations, not ungrounded narration |
| **Aurora** | Citation-first RCA framing; separable model roles (main/RCA) | Approval gate that fails *closed* — no autonomous write slips past a classifier |
| **IncidentFox** | Multi-specialist routing as a day-2 idea | Approval gate in the open core, not paywalled; maintained; deterministic eval, not GPT-4o judge |

## What's real vs simulated

- **Real:** Postgres queries, `EXPLAIN`, pg_stat_*, pgvector RAG, guarded one-shot live web
  synthetics, the policy/approval/audit layer, and the eval harness.
- **Simulated:** cloud backends (K8s/Datadog/AWS). Backends are seeded but genuinely
  queryable; mutating tools model the action, they don't hit a real cluster.

Adding authenticated production adapters — including consuming HolmesGPT toolsets or
k8sgpt's MCP scan as diagnostic tools — is the forward-deployed integration step (day 2+).
Labeled in code and README so an interviewer knows the line.
