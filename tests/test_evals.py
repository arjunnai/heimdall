from pathlib import Path

import yaml

from app.agent import IncidentAgent
from app.data import FixtureDataStore
from evals.eval import load_scenarios, render_markdown, run_suite
from evals.scorer import aggregate, score_scenario


def test_scenario_library_is_complete() -> None:
    scenarios = load_scenarios()
    assert len(scenarios) >= 15
    names = {scenario["incident_id"] for scenario in scenarios}
    assert any("drop_table" in name for name in names)
    assert any("unknown_column" in name for name in names)
    assert any("ambiguous" in name for name in names)
    assert any("duplicate_index" in name for name in names)
    assert all(Path(f"db/seeds/{scenario['seed']}.yaml").exists() for scenario in scenarios)


def test_structural_grounding_rejects_uncited_golden_evidence() -> None:
    scenario = yaml.safe_load(Path("scenarios/checkout_pool_exhaustion_001.yaml").read_text())
    result = IncidentAgent(FixtureDataStore(scenario["seed"])).investigate(scenario["description"])
    score = score_scenario(scenario, result)
    assert score.root_cause_correct
    assert score.grounded_evidence_hits == score.grounding_evidence_count
    assert aggregate([score])["evidence_grounding_accuracy"]["value"] == 1.0


def test_two_variants_produce_guardrail_delta() -> None:
    results = run_suite("fixture")
    baseline = results["variants"]["baseline"]["metrics"]
    guarded = results["variants"]["guarded"]["metrics"]
    assert baseline["unsafe_action_rate"]["value"] > guarded["unsafe_action_rate"]["value"]
    assert guarded["unsafe_action_rate"]["value"] == 0
    assert "→" in render_markdown(results)
