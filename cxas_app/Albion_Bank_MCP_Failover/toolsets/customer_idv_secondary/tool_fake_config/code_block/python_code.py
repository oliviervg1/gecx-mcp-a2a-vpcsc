"""Deterministic fake for customer_idv_secondary MCP toolset (simulates healthy secondary region)."""

from typing import Any


def fake_tool_call(tool: Any, input: dict[str, Any], callback_context: Any) -> dict[str, Any]:
    """Returns a verified FastMCP text_output record from the secondary regional endpoint."""
    customer_id = str(input.get("customer_id", "")).strip()
    if customer_id == "CUST-999":
        return {
            "status": "error",
            "error": "Secondary regional endpoint unavailable for test customer CUST-999",
        }
    return {
        "text_output": [
            {
                "status": "VERIFIED",
                "customer_id": customer_id or "CUST-101",
                "region": "europe-west1-secondary",
            }
        ]
    }
