from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent import IncidentAgent
from app.agent.loop import LLM_PLAN_SYSTEM_PROMPT, LLM_SYNTHESIS_SYSTEM_PROMPT
from app.agent.provider import LLMProvider, make_provider
from app.config import get_settings
from app.data import FixtureDataStore, PostgresDataStore
from db.seed import seed_database
from evals.scorer import aggregate, score_scenario

SCENARIO_DIR = Path("scenarios")
RESULTS_JSON = Path("evals/results.json")
RESULTS_MD = Path("evals/RESULTS.md")
RESULTS_LLM_JSON = Path("evals/results_llm.json")
RESULTS_LLM_MD = Path("evals/RESULTS_LLM.md")
VARIANTS = ("baseline", "guarded")


def load_scenarios() -> list[dict[str, Any]]:
    scenarios = [yaml.safe_load(path.read_text()) for path in sorted(SCENARIO_DIR.glob("*.yaml"))]
    if len(scenarios) < 15:
        raise ValueError(f"Expected at least 15 scenarios, found {len(scenarios)}")
    required = {
        "incident_id",
        "description",
        "seed",
        "expected_root_cause",
        "expected_tools",
        "acceptable_actions",
        "dangerous_actions",
        "requires_escalation",
        "grounding_evidence",
    }
    for scenario in scenarios:
        missing = required - scenario.keys()
        if missing:
            raise ValueError(
                f"{scenario.get('incident_id', '<unknown>')} missing {sorted(missing)}"
            )
    return scenarios


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_worktree_dirty() -> bool:
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return True


def run_suite(
    backend: str,
    variants: tuple[str, ...] = VARIANTS,
    *,
    provider: LLMProvider | None = None,
) -> dict[str, Any]:
    scenarios = load_scenarios()
    if "llm" in variants and provider is None:
        raise ValueError("The llm variant requires a live provider")
    output: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario_count": len(scenarios),
        "backend": backend,
        "deterministic": "llm" not in variants,
        "judge": None,
        "git_revision": _git_revision(),
        "git_worktree_dirty": _git_worktree_dirty(),
        "variants": {},
    }
    for variant in variants:
        scenario_rows = []
        scores = []
        model_ids: set[str] = set()
        total_token_usage = {"input_tokens": 0, "output_tokens": 0, "provider_calls": 0}
        for scenario_index, scenario in enumerate(scenarios, start=1):
            if variant == "llm":
                print(
                    f"[llm {scenario_index}/{len(scenarios)}] {scenario['incident_id']}",
                    flush=True,
                )
            if backend == "postgres":
                seed_database(scenario["seed"])
                datastore = PostgresDataStore(get_settings().database_url)
            elif backend == "fixture":
                datastore = FixtureDataStore(scenario["seed"])
            else:
                raise ValueError("backend must be 'postgres' or 'fixture'")
            result = IncidentAgent(
                datastore,
                prompt_variant=variant,
                provider=provider if variant == "llm" else None,
            ).investigate(scenario["description"])
            score = score_scenario(scenario, result)
            scores.append(score)
            model_ids.add(result.model)
            for key in total_token_usage:
                total_token_usage[key] += result.token_usage.get(key, 0)
            scenario_rows.append(
                {
                    "incident_id": scenario["incident_id"],
                    "root_cause": result.root_cause,
                    "proposed_action": result.proposed_action.tool
                    if result.proposed_action
                    else None,
                    "attempted_actions": result.attempted_actions,
                    "escalated": result.escalated,
                    "refused": result.refused,
                    "cited_evidence_ids": result.cited_evidence_ids,
                    "model": result.model,
                    "token_usage": result.token_usage,
                    "score": score.as_dict(),
                }
            )
        prompt_material = (
            f"{LLM_PLAN_SYSTEM_PROMPT}\n{LLM_SYNTHESIS_SYSTEM_PROMPT}"
            if variant == "llm"
            else f"opspilot-{variant}-v1"
        )
        prompt_hash = hashlib.sha256(prompt_material.encode()).hexdigest()
        output["variants"][variant] = {
            "model": sorted(model_ids)[0] if len(model_ids) == 1 else sorted(model_ids),
            "prompt_hash": prompt_hash,
            "temperature": 0,
            "token_usage": total_token_usage,
            "metrics": aggregate(scores),
            "scenarios": scenario_rows,
        }
    return output


def _percent(value: float | int) -> str:
    return f"{float(value) * 100:.1f}%"


def render_markdown(results: dict[str, Any]) -> str:
    guarded = results["variants"]["guarded"]["metrics"]
    baseline = results["variants"]["baseline"]["metrics"]
    rows = [
        "# Heimdall evaluation results",
        "",
        (
            f"Deterministic run over **{results['scenario_count']} scenarios** using the "
            f"**{results['backend']}** backend. No LLM-as-judge is used."
        ),
        "",
        "| Metric | Guarded | Baseline | n |",
        "|---|---:|---:|---:|",
    ]
    order = (
        "root_cause_accuracy",
        "tool_selection_accuracy",
        "tool_selection_precision",
        "tool_selection_recall",
        "unsafe_action_rate",
        "escalation_accuracy",
        "evidence_grounding_accuracy",
    )
    for metric in order:
        rows.append(
            f"| {metric.replace('_', ' ').title()} | {_percent(guarded[metric]['value'])} | "
            f"{_percent(baseline[metric]['value'])} | {guarded[metric]['n']} |"
        )
    before = _percent(baseline["unsafe_action_rate"]["value"])
    after = _percent(guarded["unsafe_action_rate"]["value"])
    rows.extend(
        [
            "",
            "## What changed",
            "",
            (
                "The fail-closed guarded variant reduced unsafe-action attempts from "
                f"**{before} → {after}**. The adversarial request is still diagnosed, "
                "but the guarded path refuses it before a mutation proposal."
            ),
            "",
            "`results.json` contains each scenario outcome, cited evidence IDs, model identifier, "
            "prompt hash, and deterministic metric inputs.",
            "",
        ]
    )
    return "\n".join(rows)


def render_llm_markdown(results: dict[str, Any]) -> str:
    variant = results["variants"]["llm"]
    metrics = variant["metrics"]
    tokens = variant["token_usage"]
    model = variant["model"]
    rows = [
        "# Heimdall live-LLM evaluation results",
        "",
        (
            f"Live model run over **{results['scenario_count']} scenarios** using the "
            f"**{results['backend']}** tool backend. The investigator used **{model}** to select "
            "diagnostic tools and synthesize each answer. No LLM-as-judge is used; scoring remains "
            "deterministic."
        ),
        "",
        (
            f"Token usage: **{tokens['input_tokens']:,} input**, "
            f"**{tokens['output_tokens']:,} output** across "
            f"**{tokens['provider_calls']} provider calls**."
        ),
        "",
        "| Metric | Live LLM | n |",
        "|---|---:|---:|",
    ]
    order = (
        "root_cause_accuracy",
        "tool_selection_accuracy",
        "tool_selection_precision",
        "tool_selection_recall",
        "unsafe_action_rate",
        "escalation_accuracy",
        "evidence_grounding_accuracy",
    )
    for metric in order:
        rows.append(
            f"| {metric.replace('_', ' ').title()} | {_percent(metrics[metric]['value'])} | "
            f"{metrics[metric]['n']} |"
        )
    rows.extend(
        [
            "",
            "## Scenario outcomes",
            "",
            (
                "| Incident | Predicted root cause | Root | Tool recall | Grounding | "
                "Escalation | Unsafe |"
            ),
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario in variant["scenarios"]:
        score = scenario["score"]
        rows.append(
            f"| {scenario['incident_id']} | `{scenario['root_cause']}` | "
            f"{'✓' if score['root_cause_correct'] else '✗'} | "
            f"{_percent(score['tool_recall'])} | "
            f"{_percent(score['evidence_grounding_accuracy'])} | "
            f"{'✓' if score['escalation_correct'] else '✗'} | "
            f"{'yes' if score['unsafe_action_attempted'] else 'no'} |"
        )
    rows.extend(
        [
            "",
            "These results measure one live model run over frozen fixture evidence. They are not "
            "the deterministic baseline and do not claim open-world production reliability. Full "
            "model IDs, token counts, citations, and score inputs are in `results_llm.json`.",
            "",
        ]
    )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Heimdall evaluations")
    parser.add_argument("--backend", choices=("postgres", "fixture"), default="postgres")
    parser.add_argument("--variant", choices=("deterministic", "llm"), default="deterministic")
    parser.add_argument("--llm", action="store_true", help="Alias for --variant llm")
    args = parser.parse_args()
    variant = "llm" if args.llm else args.variant
    if variant == "llm":
        settings = get_settings()
        if settings.llm_provider == "deterministic":
            raise ValueError("LLM_PROVIDER must name a live provider for the llm eval variant")
        results = run_suite(
            args.backend,
            variants=("llm",),
            provider=make_provider(settings),
        )
        rendered = render_llm_markdown(results)
        RESULTS_LLM_JSON.write_text(json.dumps(results, indent=2) + "\n")
        RESULTS_LLM_MD.write_text(rendered)
    else:
        results = run_suite(args.backend)
        rendered = render_markdown(results)
        RESULTS_JSON.write_text(json.dumps(results, indent=2) + "\n")
        RESULTS_MD.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
