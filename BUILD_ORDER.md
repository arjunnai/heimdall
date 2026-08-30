# OpsPilot build order

| Checkpoint | Deliverable | Status |
|---|---|---|
| CP1 | Postgres + pgvector, two seeded anomalies, FastAPI, agent loop, diagnostic MCP tools, terminal investigation | Complete |
| CP2 | 15+ deterministic scenarios, scorer, two variants, reproducible results | Complete |
| CP3 | Typed mutation boundary, signed approval tokens, policy, append-only audit | Complete |
| CP4 | Streamlit investigation timeline, evidence, Approve/Reject | Complete |
| CP5 | Recruiter-legible README, architecture, screenshots, limitations, v1 verification | Complete |

Each checkpoint is tested before the next begins. Day-2 multi-tenancy is intentionally excluded.

Final verification: `make verify` passes 14 tests, lint, and the 16-scenario two-variant fixture
evaluation. Docker Compose configuration parses successfully; Docker was unavailable on the build
host, so the containerized Postgres boot remains reproducible but was not executed in that host.
