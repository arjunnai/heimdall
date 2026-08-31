# CP8 BRIEF — domain + subdomain crawler & property health map (diagnosis-only)

Scope: **arjunrnair.com and its own subdomains ONLY.** Read `V2_BRIEF.md`,
`app/data/webprobe.py`, `app/policy/scope.py` first. Keep deterministic suites and
RESULTS.md / RESULTS_LLM.md / RESULTS_LIVE.md UNTOUCHED. Diagnosis-only stays: mutations
forbidden on live targets at the policy layer.

## Subdomain discovery — crt.sh is DOWN (~2 weeks, no ETA). DO NOT depend on it.
Use MULTIPLE resilient sources with graceful degradation (any source failing/timing out
must be skipped, never crash the run):
1. **TLS SAN (primary, no third party):** fetch the apex TLS cert, parse Subject
   Alternative Names for `*.arjunrnair.com` hosts.
2. **Passive (best-effort, each behind a short timeout, tolerant of outage):**
   certspotter (`api.certspotter.com/v1/issuances?domain=arjunrnair.com&include_subdomains=true&expand=dns_names`),
   AlienVault OTX passive DNS, Wayback CDX (`*.arjunrnair.com`).
3. **Active fallback (always works, self-contained):** resolve a small bounded
   common-subdomain wordlist (www, api, app, blog, dev, staging, cdn, mail, docs, static…);
   keep those that resolve.
Dedup all candidates.

## Scope guard — extend and HARDEN (mandatory, tested)
Every discovered/followed host must pass:
- **Registrable-domain suffix match** — host must be `arjunrnair.com` or `*.arjunrnair.com`.
  Reject look-alikes: `arjunrnair.com.evil.com`, `notarjunrnair.com`, `evil.com`. Test this
  exact bypass class — match on a real label boundary, not naive `endswith`.
- Resolve host; refuse private/loopback/link-local/metadata/reserved IPs (existing SSRF guard).
- Discovery-source hosts (certspotter/OTX/wayback/apex-cert) are a SEPARATE, explicit
  allow-list — not routed through the probe scope guard.

## Crawl (per in-scope host) — bounded + polite
- Fetch `robots.txt`; **respect Disallow** (tested). Fetch `sitemap.xml` if present.
- Follow **same-origin** links only. Caps: max depth 2, max ~25 pages/host, global page cap.
- Rate-limit (>=200ms between requests, small concurrency cap), explicit polite User-Agent.
- Per page/host: HTTP status, latency p50/p95 (samples), bytes, redirects; TLS days + DNS per host.
- **Bytes stay quarantined** (existing boundary): only count + SHA-256 survive; page content
  never enters the prompt. Links are extracted as DATA and each re-validated by the scope
  guard before any fetch.

## Health map + investigation
- Build a property health map: per host/route metrics with evidence ids
  (`metric:host:path:latency_p95`, `log:host:http_5xx`, `log:host:tls_expiring`, …).
- Agent correlates → worst route/subdomain + classification (latency regression / 5xx /
  TLS near-expiry / DNS failure). Diagnosis-only; remediation proposed, never executed.
- Write `evals/RESULTS_CRAWL.md` (labeled non-deterministic one-shot): discovered hosts,
  per-host summary table, worst-offender diagnosis with cited evidence, timestamp + target.
- Entrypoint: `make demo-crawl` (default arjunrnair.com); `CRAWL_TARGET` env override.

## Tests (pytest, MOCK the network — no live calls in unit tests)
- scope suffix-match: accepts `arjunrnair.com` + `api.arjunrnair.com`; REJECTS
  `arjunrnair.com.evil.com`, `xarjunrnair.com`, `evil.com`.
- robots.txt Disallow honored.
- depth/page caps enforced.
- discovery graceful degradation: a passive source raising/timeout falls back cleanly.
- injection boundary holds across multiple pages.
- mutation-on-live refused.

## Docs
README: add a "Crawler / property map" subsection — note the crt.sh outage and the
resilient multi-source discovery (real FDE story). Update LIMITATIONS + roadmap. Commit as CP8.

## Honesty
Never fabricate hosts, routes, or metrics. If discovery finds nothing beyond the apex,
report exactly that. Live numbers are snapshots, never the scored benchmark.

Begin now, autonomously.
