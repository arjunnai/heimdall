# Heimdall property crawl snapshot

> **One-shot live crawl, non-deterministic, not a scored benchmark.**

- Timestamp (UTC): `2026-08-31T03:27:03.865532+00:00`
- Target property: `arjunrnair.com` and its label-boundary subdomains only
- Discovery: apex TLS SAN, CertSpotter, AlienVault OTX, Wayback CDX, then bounded DNS
- crt.sh: `not queried or depended upon; service outage is tolerated by design`
- Crawl bounds: depth `2`, up to `25` pages/host, global cap `50`, `2` samples/page
- Politeness: `robots.txt honored; same-origin links; sequential; >=200 ms spacing`
- Mutation mode: `diagnosis-only; live-target policy forbids execution`

## Discovered and retained hosts

Only candidates that resolved to public addresses through the property scope guard are listed.

| Host | Confirmed by |
|---|---|
| `arjunrnair.com` | apex, certspotter, tls_san |
| `api.arjunrnair.com` | active_common_wordlist, certspotter, tls_san |
| `www.arjunrnair.com` | active_common_wordlist |
| `data.arjunrnair.com` | certspotter |
| `llm.arjunrnair.com` | certspotter |

### Discovery-source degradation

- `alienvault_otx` skipped: ReadTimeout: HTTPSConnectionPool(host='otx.alienvault.com', port=443): Read timed out. (read timeout=3)
- `wayback_cdx` skipped: HTTPError: 429 Client Error: Too Many Requests for url: https://web.archive.org/cdx/search/cdx?url=%2A.arjunrnair.com%2F%2A&output=json&fl=original&collapse=urlkey

## Per-host health summary

| Host | Pages | Worst HTTP | Worst latency p95 (ms) | DNS (ms) | TLS days |
|---|---:|---:|---:|---:|---:|
| `arjunrnair.com` | 25 | 200 | 5319.899 | 0.757 | 51.076 |
| `api.arjunrnair.com` | 1 | 404 | 129.140 | 1.685 | 51.076 |
| `www.arjunrnair.com` | 6 | 404 | 198.529 | 1.395 | 51.059 |
| `data.arjunrnair.com` | 1 | 404 | 186.905 | 1.512 | 51.074 |
| `llm.arjunrnair.com` | 1 | 200 | 175.972 | 5.678 | 51.059 |

### Crawl failures and exclusions

- No crawl fetch failure was recorded.

## Per-route health map

| Host | Route | HTTP | p50 (ms) | p95 (ms) | Bytes | Redirects | Evidence |
|---|---|---:|---:|---:|---:|---:|---|
| `arjunrnair.com` | `/` | 200 | 141.397 | 1171.437 | 27338 | 0 | `metric:arjunrnair.com:/:latency_p95` |
| `arjunrnair.com` | `/blog` | 200 | 147.118 | 1190.980 | 29505 | 0 | `metric:arjunrnair.com:/blog:latency_p95` |
| `arjunrnair.com` | `/blog/curl-api-b` | 200 | 169.628 | 2207.228 | 220923 | 0 | `metric:arjunrnair.com:/blog/curl-api-b:latency_p95` |
| `arjunrnair.com` | `/blog/reverse-engineering-work-at-a-startup` | 200 | 1173.491 | 4255.636 | 176740 | 0 | `metric:arjunrnair.com:/blog/reverse-engineering-work-at-a-startup:latency_p95` |
| `arjunrnair.com` | `/coursework` | 200 | 132.571 | 133.406 | 36871 | 0 | `metric:arjunrnair.com:/coursework:latency_p95` |
| `arjunrnair.com` | `/interviews` | 200 | 132.621 | 145.044 | 37220 | 0 | `metric:arjunrnair.com:/interviews:latency_p95` |
| `arjunrnair.com` | `/interviews/abnormal-ai` | 200 | 186.038 | 5319.899 | 61214 | 0 | `metric:arjunrnair.com:/interviews/abnormal-ai:latency_p95` |
| `arjunrnair.com` | `/interviews/abnormal-security` | 200 | 203.868 | 232.479 | 62890 | 0 | `metric:arjunrnair.com:/interviews/abnormal-security:latency_p95` |
| `arjunrnair.com` | `/interviews/abridge` | 200 | 177.507 | 198.027 | 60845 | 0 | `metric:arjunrnair.com:/interviews/abridge:latency_p95` |
| `arjunrnair.com` | `/interviews/adia` | 200 | 213.065 | 219.994 | 61718 | 0 | `metric:arjunrnair.com:/interviews/adia:latency_p95` |
| `arjunrnair.com` | `/interviews/adobe` | 200 | 197.684 | 303.093 | 91749 | 0 | `metric:arjunrnair.com:/interviews/adobe:latency_p95` |
| `arjunrnair.com` | `/interviews/adyen` | 200 | 196.917 | 258.783 | 64855 | 0 | `metric:arjunrnair.com:/interviews/adyen:latency_p95` |
| `arjunrnair.com` | `/interviews/aeonea` | 200 | 198.687 | 211.007 | 64260 | 0 | `metric:arjunrnair.com:/interviews/aeonea:latency_p95` |
| `arjunrnair.com` | `/interviews/affirm` | 200 | 217.447 | 220.730 | 85216 | 0 | `metric:arjunrnair.com:/interviews/affirm:latency_p95` |
| `arjunrnair.com` | `/interviews/agoda` | 200 | 192.214 | 199.732 | 62908 | 0 | `metric:arjunrnair.com:/interviews/agoda:latency_p95` |
| `arjunrnair.com` | `/interviews/ai2` | 200 | 232.972 | 243.042 | 60647 | 0 | `metric:arjunrnair.com:/interviews/ai2:latency_p95` |
| `arjunrnair.com` | `/interviews/airbnb` | 200 | 191.138 | 247.454 | 173985 | 0 | `metric:arjunrnair.com:/interviews/airbnb:latency_p95` |
| `arjunrnair.com` | `/interviews/airtable` | 200 | 184.497 | 238.178 | 79476 | 0 | `metric:arjunrnair.com:/interviews/airtable:latency_p95` |
| `arjunrnair.com` | `/interviews/airwallex` | 200 | 193.467 | 205.798 | 62619 | 0 | `metric:arjunrnair.com:/interviews/airwallex:latency_p95` |
| `arjunrnair.com` | `/interviews/akuna-capital` | 200 | 185.991 | 625.528 | 92529 | 0 | `metric:arjunrnair.com:/interviews/akuna-capital:latency_p95` |
| `arjunrnair.com` | `/interviews/altruist` | 200 | 190.523 | 271.028 | 60928 | 0 | `metric:arjunrnair.com:/interviews/altruist:latency_p95` |
| `arjunrnair.com` | `/interviews/amazon` | 200 | 421.529 | 442.832 | 737602 | 0 | `metric:arjunrnair.com:/interviews/amazon:latency_p95` |
| `arjunrnair.com` | `/interviews/ambience-healthcare` | 200 | 211.329 | 250.210 | 61378 | 0 | `metric:arjunrnair.com:/interviews/ambience-healthcare:latency_p95` |
| `arjunrnair.com` | `/interviews/amplitude` | 200 | 232.180 | 322.706 | 64483 | 0 | `metric:arjunrnair.com:/interviews/amplitude:latency_p95` |
| `arjunrnair.com` | `/interviews/ancestry` | 200 | 174.445 | 258.003 | 62050 | 0 | `metric:arjunrnair.com:/interviews/ancestry:latency_p95` |
| `api.arjunrnair.com` | `/` | 404 | 117.448 | 129.140 | 9 | 0 | `metric:api.arjunrnair.com:/:latency_p95` |
| `www.arjunrnair.com` | `/` | 200 | 141.651 | 147.559 | 27338 | 0 | `metric:www.arjunrnair.com:/:latency_p95` |
| `www.arjunrnair.com` | `/coursework` | 200 | 147.330 | 198.529 | 36871 | 0 | `metric:www.arjunrnair.com:/coursework:latency_p95` |
| `www.arjunrnair.com` | `/blog` | 200 | 153.916 | 158.263 | 29505 | 0 | `metric:www.arjunrnair.com:/blog:latency_p95` |
| `www.arjunrnair.com` | `/cdn-cgi/l/email-protection` | 404 | 117.011 | 130.281 | 4741 | 0 | `metric:www.arjunrnair.com:/cdn-cgi/l/email-protection:latency_p95` |
| `www.arjunrnair.com` | `/blog/reverse-engineering-work-at-a-startup` | 200 | 169.315 | 187.636 | 176740 | 0 | `metric:www.arjunrnair.com:/blog/reverse-engineering-work-at-a-startup:latency_p95` |
| `www.arjunrnair.com` | `/blog/curl-api-b` | 200 | 147.122 | 173.586 | 220923 | 0 | `metric:www.arjunrnair.com:/blog/curl-api-b:latency_p95` |
| `data.arjunrnair.com` | `/` | 404 | 158.774 | 186.905 | 28088 | 0 | `metric:data.arjunrnair.com:/:latency_p95` |
| `llm.arjunrnair.com` | `/` | 200 | 144.256 | 175.972 | 74 | 0 | `metric:llm.arjunrnair.com:/:latency_p95` |

## Worst-offender correlation

- Classification: `web_latency_regression`
- Host: `arjunrnair.com`
- Route: `/interviews/abnormal-ai`
- Summary: arjunrnair.com/interviews/abnormal-ai is the slowest route at 5319.9 ms p95.
- Correlation evidence: `metric:arjunrnair.com:/interviews/abnormal-ai:latency_p95`, `log:arjunrnair.com:/interviews/abnormal-ai:latency_high`

## Agent diagnosis

- Root cause: `web_latency_regression`
- Confidence: `0.90`
- Summary: arjunrnair.com/interviews/abnormal-ai is the slowest route at 5319.9 ms p95.
- Cited evidence IDs: `metric:arjunrnair.com:/interviews/abnormal-ai:latency_p95`, `log:arjunrnair.com:/interviews/abnormal-ai:latency_high`
- Investigator: `property-correlation-v1`

## Proposed remediation — not executed

- Automated proposal: `request_approval`
- Rationale: arjunrnair.com/interviews/abnormal-ai is the slowest route at 5319.9 ms p95.
- Status: `not executed; property-map policy forbids mutation execution`

This report is separate from every deterministic and CP7 result artifact. Hosts, routes, and measurements reflect only this run; missing data remains missing.
