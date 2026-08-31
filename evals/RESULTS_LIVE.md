# Heimdall live-site snapshot

> **One-shot live snapshot, non-deterministic, not a scored benchmark.**

- Timestamp (UTC): `2026-08-31T02:55:16.959126+00:00`
- Target: `https://arjunrnair.com/`
- Requested HTTP samples: `3`
- Successful HTTP samples: `3`
- Investigator: `claude-sonnet-4-20250514`
- Mutation mode: `diagnosis-only; execution forbidden by live-target policy`
- Deployment evidence: `unavailable (no deploy API wired; none fabricated)`

## Observed metrics

| Evidence ID | Metric | Value | Unit |
|---|---|---:|---|
| `metric:arjunrnair.com:http_status` | http_status | 200 | code |
| `metric:arjunrnair.com:ttfb_p50` | ttfb_p50 | 1200.986 | ms |
| `metric:arjunrnair.com:ttfb_p95` | ttfb_p95 | 2182.414 | ms |
| `metric:arjunrnair.com:latency_p50` | latency_p50 | 1208.970 | ms |
| `metric:arjunrnair.com:latency_p95` | latency_p95 | 2186.604 | ms |
| `metric:arjunrnair.com:response_size_bytes` | response_size_bytes | 27338.000 | bytes |
| `metric:arjunrnair.com:redirect_count` | redirect_count | 0.000 | count |
| `metric:arjunrnair.com:dns_resolve_ms` | dns_resolve_ms | 2.072 | ms |
| `metric:arjunrnair.com:tls_days_remaining` | tls_days_remaining | 51.098 | days |

## Derived probe outcomes

- `log:arjunrnair.com:latency_high` — warning: web latency regression: p95 exceeded 1000 ms
- `log:arjunrnair.com:cache_miss` — warning: cache miss observed in trusted response-header classification

## Diagnosis

- Root cause: `web_latency_regression`
- Confidence: `0.90`
- Summary: Site is available with healthy DNS and TLS, but experiencing severe latency regression with p95 response times exceeding 2000ms and cache misses.
- Cited evidence IDs: `metric:arjunrnair.com:http_status`, `metric:arjunrnair.com:latency_p95`, `log:arjunrnair.com:latency_high`, `metric:arjunrnair.com:dns_resolve_ms`, `metric:arjunrnair.com:tls_days_remaining`, `log:arjunrnair.com:cache_miss`

## Proposed remediation — not executed

- Human-only proposal: Confirm latency from a second vantage point, then separate origin/upstream TTFB from transfer time before the site owner changes configuration.
- Automated tool proposal: `none`
- Status: `not executed; live-target policy forbids mutation execution`

This report is deliberately separate from `RESULTS.md` and `RESULTS_LLM.md`. It carries no benchmark score and will vary with network and target state.
