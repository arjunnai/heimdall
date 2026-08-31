# Two-minute Heimdall demo

Use this script to record the repository without improvising or overstating the implementation.

## 0:00–0:20 — the wedge

Open the README architecture diagram. Explain: “Heimdall does not try to out-scale mature AI-SRE
projects. It makes each root-cause claim machine-checkably grounded and puts every mutation behind
one signed, fail-closed gate.”

## 0:20–0:55 — investigate

Open Streamlit with the checkout fixture selected. Submit the default incident. Point to the 93%
diagnosis, then the investigation timeline. Open **Evidence ledger** and show that the deploy and log
IDs resolve to specific tool-call IDs.

## 0:55–1:20 — stop at the boundary

Scroll to **Human decision boundary**. Show the action, exact arguments, risk, reversible flag, and
`Execution: STOPPED`. Reject once to demonstrate no state change, or approve to show the signed-token
path and appended audit entry.

## 1:20–1:45 — prove it

Open `evals/RESULTS.md`: 16 scenarios, deterministic metrics, no LLM judge, and 6.2% → 0.0% unsafe
attempts. Briefly open the DROP TABLE, hallucinated-column, ambiguous, and duplicate-index YAMLs.

## 1:45–2:00 — honest boundary

Open `LIMITATIONS.md`. Say which components are real (Postgres, EXPLAIN, pgvector, policy, token,
audit, scorer) and which cloud actions are modeled. End on the production adapter path.

