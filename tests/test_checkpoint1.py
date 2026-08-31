from dataclasses import replace

from fastapi.testclient import TestClient

from app.agent import IncidentAgent
from app.agent.provider import AnthropicProvider, LLMProvider, ProviderResponse
from app.config import Settings
from app.data import FixtureDataStore
from app.main import app
from app.tools.diagnostic import diagnostic_tool_names, registry


def test_typed_diagnostic_surface_has_real_tools() -> None:
    names = diagnostic_tool_names()
    assert {"query_metrics", "get_recent_deployments", "inspect_logs", "search_runbooks"} <= set(
        names
    )
    assert len(names) == 7
    assert all(registry.spec(name).mutating is False for name in names)


def test_pool_exhaustion_is_diagnosed_with_bound_evidence() -> None:
    result = IncidentAgent(FixtureDataStore("checkout_v42_pool")).investigate(
        "Checkout latency rose after v42 and the connection pool is timing out."
    )

    assert result.root_cause == "database_connection_pool_exhaustion"
    assert result.confidence >= 0.9
    assert "deploy:checkout:v42" in result.cited_evidence_ids
    assert "log:checkout:pool_exhausted" in result.cited_evidence_ids
    call_ids = {call.tool_call_id for call in result.trace}
    assert all(ref.tool_call_id in call_ids for ref in result.claims[0].evidence)
    assert result.proposed_action
    assert result.proposed_action.tool == "increase_connection_pool"


def test_database_anomaly_calls_real_depth_tools() -> None:
    result = IncidentAgent(FixtureDataStore("catalog_missing_index")).investigate(
        "Catalog has a slow SQL query and possible missing index on orders."
    )
    assert result.root_cause == "missing_database_index"
    assert {"explain_query", "get_index_stats", "get_table_stats"} <= {
        call.tool for call in result.trace
    }
    assert "explain:orders:customer_id:seq_scan" in result.cited_evidence_ids


def test_fastapi_investigates_fixture(monkeypatch) -> None:
    monkeypatch.setattr("app.main.settings.llm_provider", "deterministic")
    response = TestClient(app).post(
        "/investigate",
        json={
            "description": "Checkout pool exhausted after v42",
            "seed": "checkout_v42_pool",
        },
    )
    assert response.status_code == 200
    assert response.json()["root_cause"] == "database_connection_pool_exhaustion"


def test_anthropic_provider_uses_configured_base_url() -> None:
    provider = AnthropicProvider(
        Settings(
            anthropic_api_key="test-key",
            anthropic_base_url="https://gateway.example.test/anthropic",
        )
    )
    assert str(provider.client.base_url).startswith("https://gateway.example.test/anthropic")


class GroundedFakeProvider(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete(self, messages, *, temperature=0):
        self.calls += 1
        if self.calls == 1:
            return ProviderResponse(
                content=(
                    '{"tools":['
                    '{"name":"query_metrics","args":{"service":"checkout","metric":"*"}},'
                    '{"name":"get_recent_deployments","args":{"service":"checkout"}},'
                    '{"name":"inspect_logs","args":{"service":"checkout"}},'
                    '{"name":"search_runbooks","args":{"query":"pool exhaustion"}}]}'
                ),
                model="grounded-fake",
                input_tokens=10,
                output_tokens=10,
            )
        return ProviderResponse(
            content=(
                '{"root_cause":"database_connection_pool_exhaustion",'
                '"confidence":0.91,"action":"increase_connection_pool",'
                '"evidence_ids":["log:checkout:pool_exhausted"],'
                '"summary":"Pool timeout logs confirm exhaustion.",'
                '"escalated":false,"refused":false}'
            ),
            model="grounded-fake",
            input_tokens=20,
            output_tokens=10,
        )


class HallucinatingFakeProvider(GroundedFakeProvider):
    def complete(self, messages, *, temperature=0):
        response = super().complete(messages, temperature=temperature)
        if self.calls == 2:
            return replace(
                response,
                content=response.content.replace(
                    "log:checkout:pool_exhausted", "log:checkout:invented"
                ),
            )
        return response


def test_provider_output_is_constrained_to_structural_evidence() -> None:
    provider = GroundedFakeProvider()
    result = IncidentAgent(FixtureDataStore("checkout_v42_pool"), provider=provider).investigate(
        "Checkout connection pool exhausted after v42"
    )
    assert result.root_cause == "database_connection_pool_exhaustion"
    assert result.cited_evidence_ids == ["log:checkout:pool_exhausted"]
    assert [call.tool for call in result.trace] == [
        "query_metrics",
        "get_recent_deployments",
        "inspect_logs",
        "search_runbooks",
    ]
    assert result.model == "grounded-fake"
    assert result.token_usage == {
        "input_tokens": 30,
        "output_tokens": 20,
        "provider_calls": 2,
    }


def test_provider_cannot_cite_evidence_its_tools_did_not_return() -> None:
    result = IncidentAgent(
        FixtureDataStore("checkout_v42_pool"), provider=HallucinatingFakeProvider()
    ).investigate("Checkout connection pool exhausted after v42")
    assert result.root_cause == "provider_output_unverified"
    assert result.escalated
    assert result.cited_evidence_ids == []
