from __future__ import annotations

from typing import Any


def evidence_rows(result: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten structural claim citations for a readable evidence ledger."""
    rows: list[dict[str, str]] = []
    for index, claim in enumerate(result.get("claims", []), start=1):
        for evidence in claim.get("evidence", []):
            rows.append(
                {
                    "claim": f"C{index}",
                    "evidence_id": evidence["evidence_id"],
                    "tool_call_id": evidence["tool_call_id"],
                    "status": "confirmed" if claim.get("confirmed") else "unconfirmed",
                }
            )
    return rows


def timeline_rows(result: dict[str, Any]) -> list[dict[str, str | int]]:
    rows = []
    for index, call in enumerate(result.get("trace", []), start=1):
        rows.append(
            {
                "step": index,
                "tool": call["tool"],
                "tool_call_id": call["tool_call_id"],
                "evidence": len(call.get("evidence_ids", [])),
                "outcome": call.get("result_summary", {}).get("status", "ok"),
            }
        )
    return rows
