# OpsPilot build order

| Checkpoint | Deliverable | Status |
|---|---|---|
| CP1 | Postgres + pgvector, two seeded anomalies, FastAPI, agent loop, diagnostic MCP tools, terminal investigation | Complete |
| CP2 | 15+ deterministic scenarios, scorer, two variants, reproducible results | Complete |
| CP3 | Typed mutation boundary, signed approval tokens, policy, append-only audit | Complete |
| CP4 | Streamlit investigation timeline, evidence, Approve/Reject | Complete |
| CP5 | Recruiter-legible README, architecture, screenshots, limitations, v1 verification | Complete |
| CP6 | Live-provider tool planning, grounded synthesis, isolated 16-scenario LLM evaluation | Complete |

Each checkpoint is tested before the next begins. Day-2 multi-tenancy is intentionally excluded.

Final verification: `make verify` passes 17 tests, lint, and the 16-scenario two-variant deterministic
fixture evaluation. The separate 16-scenario live-LLM fixture run records 32 real provider calls in
`RESULTS_LLM.md`. Docker Compose configuration parses successfully; Docker was unavailable on the
build host, so the containerized Postgres boot remains reproducible but was not executed there.
