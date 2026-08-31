# PRIOR ART — where Heimdall sits in the AI-SRE landscape

Deep-dive via firecrawl of each incumbent's real source/docs (2026-08). Knowing the
field honestly is itself an FDE signal — including correcting a first-pass assumption.

## Correction to the naive take

A surface read ("incumbents have no evals, no approval gate") is **wrong** and would
fail in an interview. The truth: **two incumbents already ship an eval harness AND a
code-level approval gate AND real Postgres/EXPLAIN depth.** Heimdall must differentiate
on something narrower and defensible, not on "we measure and they don't."

## The incumbents (verified)

| Project | ~Stars | What it really is | Eval harness | Approval gate | DB depth |
|---------|--------|-------------------|--------------|---------------|----------|
| **HolmesGPT** (Robusta+Microsoft, CNCF) | ~3.2k | Native tool-calling loop (`max_steps=100`), ~40 YAML/Python toolsets, LiteLLM | **Yes, mature** — pytest + real-K8s fixtures, LLM-as-judge, Braintrust, per-PR CI regression | **Yes** — signed JWT tokens (args-hashed, TTL), read-only RBAC default | **Strong** — EXPLAIN, pg_stat, read-only enforced, row cap |
| **OpenSRE** (tracer-cloud) | mid | Single-agent 6-stage loop, 60+ integrations, 25+ providers | **Yes, strongest** — CloudOpsBench 452 frozen scenarios, 16 deterministic metrics (no LLM-judge), integrity guards, miss→regression loop | Code read/mutate split, but approval **narrow** (≈GitHub-issue path only) | **Very strong** — 11 databases first-class |
| **k8sgpt** (CNCF) | ~7.7k | **Not an agent** — deterministic Go scanner, ~30 analyzers, LLM only *narrates* after scan (ungrounded) | No | N/A (read-only) | K8s only |
| **Aurora** (Arvo AI) | ~400 | LangGraph supervisor + sub-agents, autonomous, 30+ tools via `terminal_run()` | **No** — asserted via demo only | Post-hoc danger classifier; **fails open** to any write it doesn't flag; **no typed read/mutate tools** | DB-adjacent RCA demoed (pg_stat_activity, RDS) |
| **IncidentFox** | mid | Multi-agent (Claude SDK + A2A), 45+ skills | Weak — fault-injection scored by GPT-4o judge | **Paywalled** out of OSS (Enterprise-only) | Light (PG/MySQL/Mongo) |
| **IncidentFox status** | — | **ARCHIVED read-only (May 2026)** — abandoned | — | — | — |

## The one gap all five share

**Structured evidence grounding, verified by the eval.** None ties a *specific claim*
to the *exact tool-output row/line* via a machine-checkable pointer (`tool_call_id` +
evidence id) with a confidence score, and then *scores that grounding* against a golden
set. HolmesGPT emits free-text and its eval scores only answer *similarity*. OpenSRE
computes a grounding *rate* but not per-claim id verification. That is Heimdall's wedge.

## What Heimdall reuses (steal the good parts)

- **HolmesGPT:** YAML toolset schema shape; signed-token approval; read-only DB toolset (EXPLAIN/pg_stat + row cap).
- **OpenSRE:** deterministic eval metrics (avoid LLM-judge); confirmed-vs-unconfirmed claim split; production-miss → regression-scenario loop (day 2).
- **k8sgpt:** its MCP server can be *consumed* as a diagnostic tool in a day-2 real adapter.
- **Aurora:** citation-first RCA framing; separable model roles.

## Where Heimdall wins (defensible in 45 minutes)

1. **Structured per-claim evidence** (`claim → evidence_id → exact row`), *scored* by the harness — the gap above.
2. **Uniform typed approval gate** over *every* mutating tool (not one path, not paywalled, not fail-open) + signed token + reversible execution + audit trail.
3. **Legible & reproducible** — a stranger runs `make eval` in 10 min and reads 15 scenarios line-by-line. A 100-step / 40-toolset product is not defensible in an interview; a tight teaching artifact is.

## Interview thesis (one line)

> The incumbents proved an agent can investigate and can be measured. Heimdall closes the
> gap none of them did — every conclusion is structurally tied to the exact evidence that
> proves it and that grounding is scored — and it makes *every* mutating action require a
> human-signed token. I don't out-scale a Microsoft-backed CNCF project; I out-ground and
> out-gate it, on a scope a reviewer can run and defend in ten minutes.

## Sources
- https://github.com/robusta-dev/holmesgpt · https://github.com/HolmesGPT/holmesgpt
- https://github.com/tracer-cloud/opensre · https://www.opensre.com
- https://github.com/k8sgpt-ai/k8sgpt · https://docs.k8sgpt.ai
- https://github.com/Arvo-AI/aurora · https://www.aurorasre.ai
- https://github.com/incidentfox/incidentfox (archived)
