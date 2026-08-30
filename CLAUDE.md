# CLAUDE.md — Working conventions for OpsPilot

This file tells Claude Code (and future-me) how to build and extend this repo.
Read `PRD.md` first for *what* and *why*; this file is *how*. When they conflict,
PRD wins on scope, this file wins on implementation style.

---

## 0. Prime directive
This is a **résumé-driven portfolio project for frontier-lab FDE roles.** Two things
matter above all:
1. **The eval harness is the star.** Spend effort accordingly (35%). Never stub it
   out to "come back later." A working agent with no evals is a failed project here.
2. **Every claim must be verifiable by opening the repo.** No invented metrics, no
   aspirational README. If `RESULTS.md` says a number, `make eval` must reproduce it.

If a change doesn't help make one of the three résumé bullets in PRD §1 true and
inspectable, don't build it in v1.

## 1. Build order — respect the checkpoints
Follow `BUILD_ORDER.md` / PRD §3. **Each checkpoint must leave the repo in a
shippable state.** Do not start Checkpoint N+1 until N runs end-to-end. Concretely:
- Do **not** build the Streamlit UI before the eval harness exists and passes.
- Do **not** add multi-tenancy (day 2) until v1 success criteria (PRD §8) are met.
- If time-constrained, cut in PRD §3 order. Announce the cut in the commit message.

## 2. Tech stack (decided — do not re-litigate)
- Python 3.11+, FastAPI, Uvicorn.
- PostgreSQL (real, Dockerized) + **pgvector** for runbook embeddings. One datastore.
- LLM via a **provider abstraction** (`app/agent/provider.py`): Anthropic primary,
  OpenAI switchable by `LLM_PROVIDER` env var. This keeps the "ran evals across
  models" bullet honest.
- MCP for the tool layer. Tools are real functions with typed signatures; the MCP
  server exposes them. Diagnostic tools hit Postgres for real.
- Streamlit for UI. **No Next.js/React** — we are not proving frontend.
- `uv` or `pip` + `requirements.txt`; `docker compose`; a `Makefile` for the verbs.

## 3. Golden rules for the agent implementation
- **Read-only vs mutating is a hard, code-level boundary**, not a prompt suggestion.
  Mutating tools physically cannot run without an approval token from the policy layer.
- **Forbidden actions** (`DROP TABLE`, `delete_database`, anything in the tenant
  `forbidden` set) are rejected by the policy layer *even if the model asks*. The
  model refusing is good; the policy refusing is the real guarantee. Test both.
- **Citations are structural, not prose.** The agent's root-cause output must carry
  machine-checkable evidence ids (e.g. `deploy:checkout:v42`, `log:...`) so the eval
  scorer can verify grounding. Don't let it hand-wave "the logs showed...".
- **Escalation is a first-class outcome.** "I'm not sure, escalating" must be a
  scoreable action, not a failure path. Ambiguous scenarios expect it.
- **Determinism for evals:** temperature 0, fixed DB seeds, pinned model ids. Record
  the model id + prompt hash in `results.json` for every run.

## 4. Tool authoring convention
Each tool lives in `app/tools/`, and declares:
```python
@tool(mutating=False, risk="low")
def query_metrics(service: str, metric: str, window: str) -> dict:
    """Return metric rows for a service over a time window. Read-only."""
    ...
    return {"rows": [...], "evidence_ids": ["metric:checkout:p95:14:15"]}
```
- Every tool returns JSON **and** an `evidence_ids` list where applicable.
- Every call is appended to the run trace: `{tool, args, result_summary, ts}`.
- Mutating tools return a *proposal* object until an approval token is present.

## 5. Eval harness convention (treat as production code)
- Scenarios are YAML in `scenarios/`, schema per PRD §4.5. One file per incident.
- `evals/eval.py` loads seeds, runs the agent headless, collects the trace, calls
  `scorer.py`, writes `results.json` + `RESULTS.md`.
- Metrics computed exactly as PRD §4.5 defines them. Don't add vanity metrics.
- `RESULTS.md` is a table: metric | value | n. Plus a short "what changed" note for
  any before/after guardrail comparison (this is the X→Y bullet — keep both runs).
- Adversarial/safety scenarios (DROP TABLE, hallucinated column, ambiguous,
  duplicate index) are **required**, not optional. A green eval that skips them is a
  red flag to interviewers.

## 6. Data / seeds
- `db/schema.sql` defines `metrics`, `deployments`, `logs` (+ any DB-scenario tables).
- Each scenario names a `seed` fixture in `db/seeds/` that loads a *real anomaly*
  (e.g. latency climbing across rows + a pool-exhaustion log line + a matching
  deploy record). The agent must be able to *derive* the answer from data, not from
  the scenario name. If the answer isn't reconstructable from the seed, the seed is wrong.

## 7. Safety / repo hygiene
- No real secrets. `.env.example` only. API keys via env at runtime.
- Mocked backends are fine, but label them clearly in code and README so an
  interviewer knows what's real (Postgres/EXPLAIN/RAG) vs simulated (K8s/Datadog).
  Honesty about this is a *strength* in the interview, not a weakness.
- Append-only audit log; never mutate past entries.
- `.gitignore` the venv, `__pycache__`, `.env`, local vector index dumps.

## 8. Commit & docs discipline
- Small, labeled commits per checkpoint (`CP1: agent loop + 4 tools, one incident e2e`).
- Update `RESULTS.md` whenever evals change; never let README claim ahead of results.
- README must have the architecture diagram **above the fold**, then a 90-second
  "what this is", then screenshots/Loom, then how-to-run, then RESULTS summary.
- Keep a `LIMITATIONS.md` (or a README section): what's mocked, what you'd do for a
  real customer. Frontier-lab interviewers respect this more than a fake-perfect demo.

## 9. Naming
Project name: **OpsPilot** (do NOT use "Sentinel" — collides with HashiCorp Sentinel
on Arjun's Yahoo résumé line). Résumé heading: *"Agentic Incident Response Platform |
Python, MCP, RAG, PostgreSQL."*

## 10. Definition of done (v1)
All PRD §8 boxes checked, all three résumé bullets verifiable by opening the repo,
`make eval` reproduces the numbers in `RESULTS.md`, and a stranger can `docker
compose up` and diagnose an incident within 10 minutes of cloning. Only then start
day-2 multi-tenancy.
