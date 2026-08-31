# Heimdall evaluation results

Deterministic run over **16 scenarios** using the **postgres** backend. No LLM-as-judge is used.

| Metric | Guarded | Baseline | n |
|---|---:|---:|---:|
| Root Cause Accuracy | 100.0% | 100.0% | 16 |
| Tool Selection Accuracy | 100.0% | 100.0% | 79 |
| Tool Selection Precision | 100.0% | 100.0% | 79 |
| Tool Selection Recall | 100.0% | 100.0% | 79 |
| Unsafe Action Rate | 0.0% | 6.2% | 16 |
| Escalation Accuracy | 100.0% | 100.0% | 16 |
| Evidence Grounding Accuracy | 96.3% | 96.3% | 27 |

## What changed

The fail-closed guarded variant reduced unsafe-action attempts from **6.2% → 0.0%**. The adversarial request is still diagnosed, but the guarded path refuses it before a mutation proposal.

`results.json` contains each scenario outcome, cited evidence IDs, model identifier, prompt hash, and deterministic metric inputs.
