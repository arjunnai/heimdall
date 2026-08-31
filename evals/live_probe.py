from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent import IncidentAgent
from app.agent.provider import make_provider
from app.config import get_settings
from app.data import WebProbeDataStore

RESULTS_LIVE_MD = Path("evals/RESULTS_LIVE.md")
HUMAN_REMEDIATION = {
    "web_latency_regression": (
        "Confirm latency from a second vantage point, then separate origin/upstream TTFB from "
        "transfer time before the site owner changes configuration."
    ),
    "web_cache_miss": (
        "Have the site owner verify cache policy and origin behavior using a longer observation "
        "window before changing cache configuration."
    ),
    "web_http_5xx": (
        "Have the site owner inspect origin and upstream error telemetry, then coordinate a "
        "reviewed rollback or fix outside Heimdall."
    ),
    "web_dns_resolution_failure": (
        "Have the DNS owner verify delegation, authoritative answers, DNSSEC, and recent record "
        "changes from an independent resolver."
    ),
    "web_tls_certificate_expiry": (
        "Notify the certificate owner and verify renewal automation and the served chain from a "
        "second public vantage point."
    ),
}


def _render_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_live_markdown(
    *,
    target: str,
    generated_at: str,
    samples: int,
    metrics: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    result: Any,
    snapshot_errors: list[dict[str, str]],
) -> str:
    rows = [
        "# Heimdall live-site snapshot",
        "",
        "> **One-shot live snapshot, non-deterministic, not a scored benchmark.**",
        "",
        f"- Timestamp (UTC): `{generated_at}`",
        f"- Target: `{target}`",
        f"- Requested HTTP samples: `{samples}`",
        f"- Successful HTTP samples: `{metrics[0]['sample_count'] if metrics else 0}`",
        f"- Investigator: `{result.model}`",
        "- Mutation mode: `diagnosis-only; execution forbidden by live-target policy`",
        "- Deployment evidence: `unavailable (no deploy API wired; none fabricated)`",
        "",
        "## Observed metrics",
        "",
        "| Evidence ID | Metric | Value | Unit |",
        "|---|---|---:|---|",
    ]
    if metrics:
        rows.extend(
            f"| `{row['evidence_id']}` | {row['metric']} | {_render_value(row['value'])} | "
            f"{row['unit']} |"
            for row in metrics
        )
    else:
        rows.append("| — | Probe returned no numeric metrics | — | — |")

    rows.extend(["", "## Derived probe outcomes", ""])
    if logs:
        rows.extend(
            f"- `{row['evidence_id']}` — {row['severity']}: {row['message']}"
            for row in logs
        )
    else:
        rows.append("- No derived outcome rows were available.")
    for error in snapshot_errors:
        rows.append(f"- Probe failure `{error['kind']}` — {error['message']}")

    rows.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Root cause: `{result.root_cause}`",
            f"- Confidence: `{result.confidence:.2f}`",
            f"- Summary: {result.summary}",
            "- Cited evidence IDs: "
            + (
                ", ".join(f"`{evidence_id}`" for evidence_id in result.cited_evidence_ids)
                if result.cited_evidence_ids
                else "none"
            ),
        ]
    )
    if result.proposed_action:
        rows.extend(
            [
                "",
                "## Proposed remediation — not executed",
                "",
                f"- Tool: `{result.proposed_action.tool}`",
                f"- Rationale: {result.proposed_action.rationale}",
                "- Status: `proposal only; live-target policy forbids execution`",
            ]
        )
    else:
        human_remediation = HUMAN_REMEDIATION.get(
            result.root_cause,
            "Escalate the cited snapshot to the site owner for verification; do not mutate the "
            "target from Heimdall.",
        )
        rows.extend(
            [
                "",
                "## Proposed remediation — not executed",
                "",
                f"- Human-only proposal: {human_remediation}",
                "- Automated tool proposal: `none`",
                "- Status: `not executed; live-target policy forbids mutation execution`",
            ]
        )
    rows.extend(
        [
            "",
            "This report is deliberately separate from `RESULTS.md` and `RESULTS_LLM.md`. "
            "It carries no benchmark score and will vary with network and target state.",
            "",
        ]
    )
    return "\n".join(rows)


def run_live_probe(target: str, samples: int, output: Path = RESULTS_LIVE_MD) -> str:
    settings = get_settings()
    provider = None if settings.llm_provider == "deterministic" else make_provider(settings)
    datastore = WebProbeDataStore(target, samples=samples)
    description = (
        f"Diagnose the current HTTPS availability, latency, DNS, TLS, and cache behavior for "
        f"the allow-listed live target {datastore.target_host}. Diagnosis only; do not execute "
        "remediation."
    )
    result = IncidentAgent(datastore, provider=provider).investigate(description)
    metrics = datastore.query_metrics(datastore.target_host, "*", "24h")
    logs = datastore.inspect_logs(datastore.target_host, None, "24h", None)
    snapshot = datastore.snapshot
    generated_at = datetime.now(UTC).isoformat()
    markdown = render_live_markdown(
        target=datastore.target_url,
        generated_at=generated_at,
        samples=samples,
        metrics=metrics,
        logs=logs,
        result=result,
        snapshot_errors=list(asdict(snapshot)["errors"]) if snapshot else [],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown)
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one non-deterministic live-site diagnosis")
    parser.add_argument("--target", default="https://arjunrnair.com")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, default=RESULTS_LIVE_MD)
    args = parser.parse_args()
    markdown = run_live_probe(args.target, args.samples, args.output)
    print(markdown)


if __name__ == "__main__":
    main()
