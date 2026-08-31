from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from app.agent import PropertyHealthAgent
from app.data import PropertyCrawler, PropertyHealthDataStore, SubdomainDiscovery
from app.policy.scope import PROPERTY_ROOT_DOMAIN, LiveScopeGuard, ScopeRefusal

RESULTS_CRAWL_MD = Path("evals/RESULTS_CRAWL.md")

HUMAN_REMEDIATION = {
    "web_latency_regression": (
        "Confirm the worst route from another vantage point, then separate origin TTFB from "
        "transfer time before the property owner changes configuration."
    ),
    "web_http_5xx": (
        "Have the property owner inspect origin/upstream errors for the cited route and coordinate "
        "a reviewed fix or rollback outside Heimdall."
    ),
    "web_tls_certificate_expiry": (
        "Notify the certificate owner and verify renewal automation and the served chain from a "
        "second public vantage point."
    ),
    "web_dns_resolution_failure": (
        "Have the DNS owner verify delegation and authoritative answers from an independent "
        "resolver."
    ),
}


def _number(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _route_evidence_id(host: str, path: str) -> str:
    return f"metric:{host}:{quote(path or '/', safe='/')}:latency_p95"


def render_crawl_markdown(health_map: Any, result: Any) -> str:
    worst = health_map.worst_offender()
    rows = [
        "# Heimdall property crawl snapshot",
        "",
        "> **One-shot live crawl, non-deterministic, not a scored benchmark.**",
        "",
        f"- Timestamp (UTC): `{health_map.generated_at}`",
        f"- Target property: `{health_map.apex}` and its label-boundary subdomains only",
        "- Discovery: apex TLS SAN, CertSpotter, AlienVault OTX, Wayback CDX, then bounded DNS",
        "- crt.sh: `not queried or depended upon; service outage is tolerated by design`",
        (
            f"- Crawl bounds: depth `{health_map.max_depth}`, up to "
            f"`{health_map.max_pages_per_host}` pages/host, global cap "
            f"`{health_map.global_page_cap}`, `{health_map.samples_per_page}` samples/page"
        ),
        "- Politeness: `robots.txt honored; same-origin links; sequential; >=200 ms spacing`",
        "- Mutation mode: `diagnosis-only; live-target policy forbids execution`",
        "",
        "## Discovered and retained hosts",
        "",
        (
            "Only candidates that resolved to public addresses through the property scope guard "
            "are listed."
        ),
        "",
        "| Host | Confirmed by |",
        "|---|---|",
    ]
    if health_map.discovery.hosts:
        rows.extend(
            f"| `{item.host}` | {', '.join(item.sources)} |"
            for item in health_map.discovery.hosts
        )
    else:
        rows.append("| — | No host passed discovery and scope validation |")

    rows.extend(["", "### Discovery-source degradation", ""])
    if health_map.discovery.source_errors:
        rows.extend(
            f"- `{source}` skipped: {error}"
            for source, error in sorted(health_map.discovery.source_errors.items())
        )
    else:
        rows.append("- No discovery source reported an error in this run.")

    rows.extend(
        [
            "",
            "## Per-host health summary",
            "",
            "| Host | Pages | Worst HTTP | Worst latency p95 (ms) | DNS (ms) | TLS days |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for host in health_map.hosts:
        status = max((page.status_code for page in host.pages), default=None)
        latency = max((page.latency_p95_ms for page in host.pages), default=None)
        rows.append(
            f"| `{host.host}` | {len(host.pages)} | {_number(status)} | {_number(latency)} | "
            f"{_number(host.dns_resolve_ms)} | {_number(host.tls_days_remaining)} |"
        )
    if not health_map.hosts:
        rows.append("| — | 0 | — | — | — | — |")

    crawl_failures = [
        (host.host, error) for host in health_map.hosts for error in host.errors
    ]
    rows.extend(["", "### Crawl failures and exclusions", ""])
    if crawl_failures:
        rows.extend(
            f"- `{host}` `{error['kind']}`: {error['message']}"
            for host, error in crawl_failures
        )
    else:
        rows.append("- No crawl fetch failure was recorded.")
    for host in health_map.hosts:
        if host.robots_disallowed:
            rows.append(
                f"- `{host.host}` robots exclusions honored: "
                + ", ".join(f"`{path}`" for path in host.robots_disallowed)
            )

    rows.extend(
        [
            "",
            "## Per-route health map",
            "",
            "| Host | Route | HTTP | p50 (ms) | p95 (ms) | Bytes | Redirects | Evidence |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    pages = [page for host in health_map.hosts for page in host.pages]
    for page in pages:
        evidence_id = _route_evidence_id(page.host, page.path)
        rows.append(
            f"| `{page.host}` | `{page.path}` | {page.status_code} | "
            f"{page.latency_p50_ms:.3f} | {page.latency_p95_ms:.3f} | "
            f"{page.response_size_bytes:.0f} | {page.redirect_count} | `{evidence_id}` |"
        )
    if not pages:
        rows.append("| — | — | — | — | — | — | — | No route measurements available |")

    rows.extend(
        [
            "",
            "## Worst-offender correlation",
            "",
            f"- Classification: `{worst.classification}`",
            f"- Host: `{worst.host}`",
            f"- Route: `{worst.route or 'host-level'}`",
            f"- Summary: {worst.summary}",
            "- Correlation evidence: "
            + (
                ", ".join(f"`{item}`" for item in worst.evidence_ids)
                if worst.evidence_ids
                else "none"
            ),
            "",
            "## Agent diagnosis",
            "",
            f"- Root cause: `{result.root_cause}`",
            f"- Confidence: `{result.confidence:.2f}`",
            f"- Summary: {result.summary}",
            "- Cited evidence IDs: "
            + (
                ", ".join(f"`{item}`" for item in result.cited_evidence_ids)
                if result.cited_evidence_ids
                else "none"
            ),
            f"- Investigator: `{result.model}`",
            "",
            "## Proposed remediation — not executed",
            "",
        ]
    )
    if result.proposed_action:
        rows.extend(
            [
                f"- Automated proposal: `{result.proposed_action.tool}`",
                f"- Rationale: {result.proposed_action.rationale}",
            ]
        )
    else:
        rows.extend(
            [
                "- Human-only proposal: "
                + HUMAN_REMEDIATION.get(
                    worst.classification,
                    "Escalate the cited snapshot to the property owner for verification.",
                ),
                "- Automated proposal: `none`",
            ]
        )
    rows.extend(
        [
            "- Status: `not executed; property-map policy forbids mutation execution`",
            "",
            "This report is separate from every deterministic and CP7 result artifact. Hosts, "
            "routes, and measurements reflect only this run; missing data remains missing.",
            "",
        ]
    )
    return "\n".join(rows)


def run_crawl(
    target: str,
    *,
    output: Path = RESULTS_CRAWL_MD,
    max_hosts: int = 12,
    global_page_cap: int = 50,
    samples_per_page: int = 2,
) -> str:
    parsed = urlsplit(target if "://" in target else f"https://{target}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != PROPERTY_ROOT_DOMAIN:
        raise ScopeRefusal("CRAWL_TARGET must be the arjunrnair.com apex")
    guard = LiveScopeGuard.for_arjunrnair_property()
    discovery = SubdomainDiscovery(property_guard=guard, max_hosts=max_hosts).discover()
    health_map = PropertyCrawler(
        scope_guard=guard,
        global_page_cap=global_page_cap,
        samples_per_page=samples_per_page,
    ).crawl(discovery)
    datastore = PropertyHealthDataStore(health_map)
    result = PropertyHealthAgent(datastore).investigate(
        "Correlate the complete arjunrnair.com property health map. Identify and classify the "
        "worst observed subdomain or route using only cited crawl evidence. Diagnosis only; do "
        "not execute remediation."
    )
    markdown = render_crawl_markdown(health_map, result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown)
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded live property crawl")
    parser.add_argument("--target", default=PROPERTY_ROOT_DOMAIN)
    parser.add_argument("--output", type=Path, default=RESULTS_CRAWL_MD)
    parser.add_argument("--max-hosts", type=int, default=12)
    parser.add_argument("--global-page-cap", type=int, default=50)
    parser.add_argument("--samples-per-page", type=int, default=2)
    args = parser.parse_args()
    print(
        run_crawl(
            args.target,
            output=args.output,
            max_hosts=args.max_hosts,
            global_page_cap=args.global_page_cap,
            samples_per_page=args.samples_per_page,
        )
    )


if __name__ == "__main__":
    main()
