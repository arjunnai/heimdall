from ui.view_model import evidence_rows, timeline_rows


def test_ui_view_models_preserve_structural_ids() -> None:
    result = {
        "claims": [
            {
                "confirmed": True,
                "evidence": [{"evidence_id": "log:x:1", "tool_call_id": "call_1"}],
            }
        ],
        "trace": [
            {
                "tool": "inspect_logs",
                "tool_call_id": "call_1",
                "evidence_ids": ["log:x:1"],
                "result_summary": {"status": "ok"},
            }
        ],
    }
    assert evidence_rows(result)[0]["evidence_id"] == "log:x:1"
    assert timeline_rows(result)[0]["evidence"] == 1
