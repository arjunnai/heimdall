from fastapi.testclient import TestClient

from app.agent import IncidentAgent
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


def test_fastapi_investigates_fixture() -> None:
    response = TestClient(app).post(
        "/investigate",
        json={
            "description": "Checkout pool exhausted after v42",
            "seed": "checkout_v42_pool",
        },
    )
    assert response.status_code == 200
    assert response.json()["root_cause"] == "database_connection_pool_exhaustion"
