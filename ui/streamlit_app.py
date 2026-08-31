# ruff: noqa: E501
from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

from ui.view_model import evidence_rows, timeline_rows

API_URL = os.getenv("OPSPILOT_API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="Heimdall · Incident Control",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Chivo:wght@400;500;600;700&family=Public+Sans:wght@400;500;600&display=swap');

:root {
  --surface: oklch(0.175 0.012 155);
  --surface-raised: oklch(0.215 0.014 155);
  --ink: oklch(0.92 0.008 90);
  --ink-muted: oklch(0.68 0.018 145);
  --line: oklch(0.34 0.018 150);
  --signal: oklch(0.79 0.14 82);
  --safe: oklch(0.74 0.11 155);
  --danger: oklch(0.68 0.17 28);
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
}

.stApp { background: var(--surface); color: var(--ink); font-family: 'Public Sans', sans-serif; }
header[data-testid="stHeader"] { background: color-mix(in oklch, var(--surface) 92%, transparent); }
[data-testid="stSidebar"] { background: oklch(0.145 0.011 155); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] h1 { color: var(--ink); }
h1, h2, h3 { font-family: 'Chivo', sans-serif; letter-spacing: -0.025em; color: var(--ink); }
h1 { font-size: 2.1rem; font-weight: 600; }
h2 { font-size: 1.35rem; font-weight: 600; }
p, label, [data-testid="stCaptionContainer"] { color: var(--ink-muted); }

.ops-kicker { color: var(--signal); font: 600 0.72rem 'Chivo', sans-serif; letter-spacing: 0.16em; text-transform: uppercase; }
.ops-header { border-bottom: 1px solid var(--line); padding-bottom: var(--space-lg); margin-bottom: var(--space-xl); }
.ops-subhead { max-width: 68ch; font-size: 0.98rem; line-height: 1.65; }
.posture { display: flex; gap: var(--space-lg); flex-wrap: wrap; margin-top: var(--space-md); }
.posture span { color: var(--ink); font-size: 0.78rem; }
.posture b { color: var(--safe); font-weight: 600; }
.decision-boundary { border: 1px solid var(--signal); background: oklch(0.22 0.025 82); padding: var(--space-lg); margin: var(--space-lg) 0; }
.decision-boundary strong { color: var(--signal); font-family: 'Chivo', sans-serif; }
.state-refused { color: var(--danger); font-weight: 600; }
.state-escalated { color: var(--signal); font-weight: 600; }
.metric-value { font: 600 1.8rem 'Chivo', sans-serif; color: var(--ink); }
.metric-label { color: var(--ink-muted); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; }

.stButton > button { border-radius: 2px; border: 1px solid var(--line); font-family: 'Chivo', sans-serif; min-height: 42px; }
.stButton > button[kind="primary"] { background: var(--signal); color: oklch(0.18 0.025 82); border-color: var(--signal); }
[data-testid="stBaseButton-primary"] p { color: oklch(0.18 0.025 82); }
[data-testid="stBaseButton-secondary"] { background: transparent; border-color: var(--line); }
[data-testid="stBaseButton-secondary"] p { color: var(--ink); }
.stTextArea textarea, .stSelectbox div[data-baseweb="select"] { border-radius: 2px; background: var(--surface-raised); }
[data-testid="stDataFrame"] { border: 1px solid var(--line); }
[data-testid="stMetricValue"] { font-family: 'Chivo', sans-serif; }

@media (max-width: 760px) {
  h1 { font-size: 1.65rem; }
  .ops-header { margin-bottom: var(--space-lg); }
  .decision-boundary { padding: var(--space-md); }
}
</style>
""",
    unsafe_allow_html=True,
)


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=45)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict[str, Any]:
    response = requests.get(f"{API_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.markdown('<div class="ops-kicker">System posture</div>', unsafe_allow_html=True)
    st.title("Heimdall")
    st.caption("Evidence-grounded investigation with a fail-closed mutation boundary.")
    st.divider()
    seed_mode = st.toggle("Use seeded demo", value=True)
    seed = st.selectbox(
        "Incident fixture",
        [
            "checkout_v42_pool",
            "catalog_missing_index",
            "payments_memory_leak",
            "checkout_ambiguous",
        ],
        disabled=not seed_mode,
    )
    st.caption(
        "Fixture mode is deterministic. Postgres mode queries the live configured datastore."
    )
    st.divider()
    try:
        health = api_get("/health")
        st.success(f"API · {health['status'].upper()}")
    except requests.RequestException:
        st.error("API · OFFLINE")
    st.caption(f"Endpoint: {API_URL}")

st.markdown(
    """
<div class="ops-header">
  <div class="ops-kicker">Incident control / v1</div>
  <h1>Investigate first. Mutate only with authority.</h1>
  <p class="ops-subhead">Every conclusion below resolves to a tool call and an exact evidence ID.
  Read-only diagnostics run automatically; state changes stop at a signed human approval boundary.</p>
  <div class="posture"><span>DIAGNOSTICS <b>AUTO</b></span><span>MUTATIONS <b>HUMAN-GATED</b></span><span>AUDIT <b>APPEND-ONLY</b></span></div>
</div>
""",
    unsafe_allow_html=True,
)

default_incident = (
    "Checkout p95 latency rose from 200ms to 1.8s after v42; connection pool timeouts are firing."
)
description = st.text_area(
    "Incident signal",
    value=default_incident,
    height=110,
    help="Paste an alert, operator observation, or incident summary.",
)

if st.button("Begin investigation", type="primary", width="stretch"):
    if not description.strip():
        st.warning("Add an incident signal before investigating.")
    else:
        payload: dict[str, Any] = {"description": description, "prompt_variant": "guarded"}
        if seed_mode:
            payload["seed"] = seed
        try:
            with st.status(
                "Correlating telemetry, logs, deployments, and runbooks…", expanded=True
            ):
                result = api_post("/investigate", payload)
                st.write(f"Collected {len(result['trace'])} tool observations.")
                st.write(f"Bound {len(result['cited_evidence_ids'])} evidence references.")
            st.session_state["investigation"] = result
            st.session_state.pop("decision", None)
        except requests.RequestException as exc:
            st.error(f"Investigation failed: {exc}")

result = st.session_state.get("investigation")
if result:
    st.divider()
    state_col, confidence_col, evidence_col, tools_col = st.columns(4)
    state_col.metric("Outcome", "ESCALATED" if result["escalated"] else "DIAGNOSED")
    confidence_col.metric("Confidence", f"{result['confidence']:.0%}")
    evidence_col.metric("Evidence IDs", len(result["cited_evidence_ids"]))
    tools_col.metric("Tool calls", len(result["trace"]))

    st.subheader(result["root_cause"].replace("_", " ").title())
    st.write(result["summary"])
    if result["refused"]:
        st.markdown('<p class="state-refused">FORBIDDEN ACTION REFUSED</p>', unsafe_allow_html=True)
    if result["escalated"]:
        st.markdown(
            '<p class="state-escalated">HUMAN ESCALATION REQUIRED</p>', unsafe_allow_html=True
        )

    timeline_tab, evidence_tab, audit_tab = st.tabs(
        ["Investigation timeline", "Evidence ledger", "Audit"]
    )
    with timeline_tab:
        st.dataframe(timeline_rows(result), width="stretch", hide_index=True)
    with evidence_tab:
        rows = evidence_rows(result)
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No confirmed evidence is available. Escalate rather than infer.")
    with audit_tab:
        try:
            events = api_get("/audit")["events"]
            st.dataframe(events, width="stretch", hide_index=True)
        except requests.RequestException as exc:
            st.warning(f"Audit unavailable: {exc}")

    proposal = result.get("proposed_action")
    if proposal and not st.session_state.get("decision"):
        st.markdown(
            f"""
<div class="decision-boundary">
  <div class="ops-kicker">Human decision boundary</div>
  <strong>{proposal["tool"].replace("_", " ").title()}</strong>
  <p>{proposal["rationale"]}</p>
  <p>Risk: {proposal["risk"].upper()} · Reversible: {"YES" if proposal["reversible"] else "NO"} · Execution: STOPPED</p>
</div>
""",
            unsafe_allow_html=True,
        )
        st.json(proposal["args"], expanded=False)
        approve_col, reject_col = st.columns([1, 1])
        if approve_col.button("Approve signed action", type="primary", width="stretch"):
            try:
                decision = api_post(
                    "/approve",
                    {
                        "tool_call_id": proposal["tool_call_id"],
                        "approve": True,
                        "actor": "ui:oncall",
                    },
                )
                st.session_state["decision"] = decision
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Approval failed: {exc}")
        if reject_col.button("Reject and halt", width="stretch"):
            try:
                decision = api_post(
                    "/approve",
                    {
                        "tool_call_id": proposal["tool_call_id"],
                        "approve": False,
                        "actor": "ui:oncall",
                    },
                )
                st.session_state["decision"] = decision
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Rejection failed: {exc}")

    if st.session_state.get("decision"):
        decision = st.session_state["decision"]
        if decision["status"] == "approved":
            st.success("Approved token verified. Mutation executed and appended to audit.")
        else:
            st.info("Proposal rejected. No state change was executed.")
