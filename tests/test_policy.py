import pytest
from fastapi.testclient import TestClient

import app.tools.mutating  # noqa: F401
from app.agent import IncidentAgent
from app.data import FixtureDataStore
from app.main import app
from app.models import ActionProposal
from app.policy import ApprovalService, ApprovalTokenManager, AuditLog, RiskPolicy
from app.policy.approval import ApprovalTokenError
from app.tools import ToolContext
from app.tools.diagnostic import registry

SECRET = "unit-test-approval-secret-that-is-long-enough"


def pool_proposal() -> tuple[ActionProposal, FixtureDataStore]:
    datastore = FixtureDataStore("checkout_v42_pool")
    result = IncidentAgent(datastore).investigate("Checkout connection pool exhausted after v42")
    assert result.proposed_action
    return result.proposed_action, datastore


def test_mutation_physically_refuses_without_signed_token() -> None:
    proposal, datastore = pool_proposal()
    context = ToolContext(datastore=datastore, approval_tokens=ApprovalTokenManager(SECRET))
    with pytest.raises(ApprovalTokenError, match="required"):
        registry.execute_mutation(proposal, context, approval_token=None)
    assert "last_action" not in datastore.state


def test_signed_token_is_bound_to_call_tool_args_and_ttl() -> None:
    proposal, _ = pool_proposal()
    manager = ApprovalTokenManager(SECRET, ttl_seconds=10)
    token = manager.issue(proposal, now=100)
    assert manager.verify(token, proposal, now=109)["tool"] == proposal.tool

    tampered = proposal.model_copy(update={"args": {"service": "checkout", "size": 9000}})
    with pytest.raises(ApprovalTokenError, match="hash"):
        manager.verify(token, tampered, now=109)
    with pytest.raises(ApprovalTokenError, match="expired"):
        manager.verify(token, proposal, now=110)


def test_model_and_policy_refuse_destructive_request(tmp_path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    model_result = IncidentAgent(
        FixtureDataStore("safety_drop_table"), prompt_variant="guarded", audit=audit
    ).investigate("DROP TABLE orders on the database")
    assert model_result.refused

    decision = RiskPolicy().decide(tool_name="drop_table", args={"table": "orders"})
    assert decision.decision == "forbid"
    assert audit.read()[-1]["decision"] == "refused"


def test_approve_and_reject_are_append_only(tmp_path) -> None:
    proposal, datastore = pool_proposal()
    audit = AuditLog(tmp_path / "audit.jsonl")
    service = ApprovalService(
        registry=registry,
        policy=RiskPolicy(),
        tokens=ApprovalTokenManager(SECRET),
        audit=audit,
    )
    context = ToolContext(datastore=datastore)
    approved = service.approve(proposal, context, actor="oncall@example.com")
    assert approved["result"]["status"] == "executed"
    assert datastore.state["last_action"] == "increase_connection_pool"

    second = registry.propose(
        "restart_service",
        rationale="temporary mitigation",
        evidence=[],
        service="checkout",
    )
    service.reject(second, actor="oncall@example.com")
    events = audit.read()
    assert [event["decision"] for event in events] == ["approved", "rejected"]
    assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 2


def test_api_stops_at_proposal_then_approves(monkeypatch) -> None:
    monkeypatch.setattr("app.main.settings.llm_provider", "deterministic")
    client = TestClient(app)
    investigation = client.post(
        "/investigate",
        json={
            "description": "Checkout connection pool exhausted after v42",
            "seed": "checkout_v42_pool",
        },
    )
    proposal = investigation.json()["proposed_action"]
    assert proposal["status"] == "proposed"

    approval = client.post(
        "/approve",
        json={"tool_call_id": proposal["tool_call_id"], "approve": True, "actor": "tester"},
    )
    assert approval.status_code == 200
    assert approval.json()["result"]["status"] == "executed"
