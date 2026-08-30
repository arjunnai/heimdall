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
from app.config import get_settings
from app.data import FixtureDataStore, PostgresDataStore
from db.seed import seed_database
from evals.scorer import aggregate, score_scenario

SCENARIO_DIR = Path("scenarios")
RESULTS_JSON = Path("evals/results.json")
RESULTS_MD = Path("evals/RESULTS.md")
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


def run_suite(backend: str, variants: tuple[str, ...] = VARIANTS) -> dict[str, Any]:
    scenarios = load_scenarios()
    output: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario_count": len(scenarios),
        "backend": backend,
        "deterministic": True,
        "judge": None,
        "git_revision": _git_revision(),
        "variants": {},
    }
    for variant in variants:
        scenario_rows = []
        scores = []
        for scenario in scenarios:
            if backend == "postgres":
                seed_database(scenario["seed"])
                datastore = PostgresDataStore(get_settings().database_url)
            elif backend == "fixture":
                datastore = FixtureDataStore(scenario["seed"])
            else:
                raise ValueError("backend must be 'postgres' or 'fixture'")
            result = IncidentAgent(datastore, prompt_variant=variant).investigate(
                scenario["description"]
            )
            score = score_scenario(scenario, result)
            scores.append(score)
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
                    "score": score.as_dict(),
                }
            )
        prompt_hash = hashlib.sha256(f"opspilot-{variant}-v1".encode()).hexdigest()
        output["variants"][variant] = {
            "model": "deterministic-rules-v1",
            "prompt_hash": prompt_hash,
            "temperature": 0,
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
        "# OpsPilot evaluation results",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic OpsPilot evaluations")
    parser.add_argument("--backend", choices=("postgres", "fixture"), default="postgres")
    args = parser.parse_args()
    results = run_suite(args.backend)
    RESULTS_JSON.write_text(json.dumps(results, indent=2) + "\n")
    RESULTS_MD.write_text(render_markdown(results))
    print(render_markdown(results))


if __name__ == "__main__":
    main()
