# BUILD BRIEF — implementation directive (for the coding agent)

You are implementing **OpsPilot** v1. Authoritative docs, read ALL before coding:
`PRD.md` (what/why + checkpoints), `ARCHITECTURE.md` (target design + the wedge),
`CLAUDE.md` (implementation conventions — obey exactly), `PRIOR_ART.md` (why the design
is shaped this way). On conflict: PRD wins on scope, CLAUDE.md wins on style.

## Mandate
Build v1 Checkpoints 1–5 from PRD §3, in order. Each checkpoint must leave the repo
shippable and runnable before starting the next. Announce any cut in the commit message.

## Effort allocation (hard rule from PRD)
40% agent/tools · **35% eval harness (the star — never stub)** · 15% safety/HITL · 10% UI.

## Non-negotiables (these are what make the project defensible)
1. **Typed tool boundary in code:** `@tool(mutating=bool, risk=...)`. Mutating tools return
   a *proposal* and physically cannot execute without a signed approval token from the
   policy layer. Not a prompt suggestion — a code guarantee. Test both model-refuses and
   policy-refuses paths.
2. **Structured per-claim evidence (the differentiator):** every diagnostic tool returns
   `evidence_ids` bound to its call; the agent's root-cause output references those ids;
   `scorer.py` verifies cited ids against each scenario's `grounding_evidence`. No prose-only
   citations.
3. **Signed approval tokens:** HMAC over (tool_call_id + tool name + args_hash) + short TTL,
   verified before any mutation. Append-only audit log for every outcome
   (auto/approved/rejected/refused/escalated).
4. **Eval harness:** ≥15 YAML scenarios (schema in PRD §4.5), `eval.py` + `scorer.py`,
   **deterministic metrics only — no LLM-as-judge.** Metrics exactly per PRD §4.5 incl.
   evidence-grounding accuracy. Required adversarial cases: DROP TABLE (refuse), hallucinated
   column (no fabrication), ambiguous (escalate), duplicate index (no-op). Support ≥2
   model/prompt variants → the before/after X→Y guardrail number in `RESULTS.md`.
5. **Real data:** Postgres (Dockerized) + pgvector, one datastore. `db/schema.sql`,
   per-scenario seed fixtures that encode a *real anomaly* derivable from the data alone.
   `explain_query` uses real `EXPLAIN (FORMAT JSON)`; stats tools hit pg_stat_*.

## Stack (decided — do not re-litigate)
Python 3.11+, FastAPI/Uvicorn, PostgreSQL+pgvector, MCP tool layer, provider abstraction
(`app/agent/provider.py`, Anthropic primary, OpenAI switchable via `LLM_PROVIDER`),
Streamlit UI (no React), `docker compose`, `Makefile` (seed/run/eval/demo), `requirements.txt`.

## Repo layout: follow PRD §7 exactly.

## Hygiene
`.gitignore` (venv, __pycache__, .env, vector dumps). `.env.example` only — no real secrets.
Label mocked backends (K8s/Datadog) clearly vs real (Postgres/EXPLAIN/RAG). Keep
`BUILD_ORDER.md` updated with checkpoint progress. Small labeled commits per checkpoint
(`CP1: ...`). Never let README/RESULTS claim ahead of what `make eval` reproduces.

## Start now
Begin Checkpoint 1: schema + ≥2 seeded anomalies, FastAPI, agent loop, 4 diagnostic MCP
tools, one incident diagnosed end-to-end in the terminal with cited evidence. Work
autonomously; do not stop for approval.
