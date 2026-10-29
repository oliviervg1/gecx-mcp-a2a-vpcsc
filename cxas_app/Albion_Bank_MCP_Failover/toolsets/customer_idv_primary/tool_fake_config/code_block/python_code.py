"""Deterministic fake for customer_idv_primary MCP toolset (simulates primary regional outage)."""

from typing import Any


def fake_tool_call(tool: Any, input: dict[str, Any], callback_context: Any) -> dict[str, Any]:
    """Simulates a call-time MCP session initialization error on the primary regional endpoint."""
    return {
        "status": "error",
        "error": "Failed to initialize MCP session on primary regional endpoint (europe-west2-primary)",
    }
