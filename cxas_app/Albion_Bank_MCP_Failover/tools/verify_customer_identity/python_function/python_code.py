# Controller tool for idv_sub_agent: verifies customer identity via primary MCP with secondary failover.
# CXAS runtime globals: `context` (session state) and `tools` (MCP toolsets) are injected by the sandbox (no imports).
# ruff: noqa: F821

import logging
from typing import Any

logger = logging.getLogger(__name__)


def verify_customer_identity(customer_id: str = "") -> dict[str, str]:
    """Verifies a customer's identity via the primary MCP toolset with secondary failover.

    Call this tool whenever the customer asks to verify their identity or access
    account balances requiring identity verification.

    Args:
        customer_id: The customer identifier spoken or entered by the customer (for example, CUST-101).

    Returns:
        dict: A single-key dictionary containing the agent_action instruction for the model.
    """
    try:
        # Step 1: Prompt for the customer ID if it has not been provided yet.
        cleaned_id = customer_id.strip()
        if not cleaned_id:
            return {
                "agent_action": (
                    "Ask the customer to provide their customer ID so you can verify their identity."
                )
            }

        # Step 2: Attempt verification against the primary regional MCP toolset first.
        primary_record = _call_regional_mcp(
            tools.customer_idv_primary_verify_customer, cleaned_id
        )
        if primary_record is not None:
            context.state["idv_status"] = "VERIFIED"
            context.state["idv_region"] = primary_record["region"]
            return _format_verified_action(cleaned_id, primary_record, failed_over=False)

        # Step 3: Fail over automatically to the secondary regional MCP toolset.
        secondary_record = _call_regional_mcp(
            tools.customer_idv_secondary_verify_customer, cleaned_id
        )
        if secondary_record is not None:
            context.state["idv_status"] = "VERIFIED"
            context.state["idv_region"] = secondary_record["region"]
            return _format_verified_action(cleaned_id, secondary_record, failed_over=True)

        # Step 4: Both regional MCP endpoints are unavailable; degrade gracefully.
        context.state["idv_status"] = "UNAVAILABLE"
        context.state["escalation_reason"] = "IDV_REGIONS_UNAVAILABLE"
        context.state["call_complete"] = "true"
        return {
            "agent_action": (
                "Apologize that the automated verification service is temporarily unavailable "
                "and let the customer know a banking specialist will assist them shortly."
            )
        }
    except Exception:
        logger.exception("verify_customer_identity failed")
        context.state["idv_status"] = "UNAVAILABLE"
        context.state["escalation_reason"] = "IDV_SYSTEM_ERROR"
        context.state["call_complete"] = "true"
        return {
            "agent_action": (
                "Apologize that the automated verification service encountered a technical issue "
                "and let the customer know a banking specialist will assist them shortly."
            )
        }


def _call_regional_mcp(mcp_tool_fn: Any, customer_id: str) -> dict[str, Any] | None:
    """Invokes a regional MCP toolset operation and returns the verified record if healthy."""
    try:
        resp = mcp_tool_fn({"customer_id": customer_id})
        if not _is_mcp_call_successful(resp):
            return None
        record = _extract_verification_record(resp)
        if "region" not in record:
            return None
        return record
    except Exception:
        logger.warning("Regional MCP call failed", exc_info=True)
        return None


def _is_mcp_call_successful(resp: Any) -> bool:
    """Checks both HTTP transport status and call-time MCP error envelopes."""
    if not resp.ok:
        return False
    if not resp.text:
        return False
    body = resp.json()
    if body.get("status") == "error":
        return False
    return True


def _extract_verification_record(resp: Any) -> dict[str, Any]:
    """Unwraps the FastMCP text_output dictionary envelope returned by CXAS."""
    body = resp.json()
    text_output = body.get("text_output")
    if not text_output:
        return {}
    return text_output[0]


def _format_verified_action(
    customer_id: str,
    record: dict[str, Any],
    failed_over: bool,
) -> dict[str, str]:
    """Builds the model-facing agent_action directive from the verified record."""
    route_note = "secondary regional failover" if failed_over else "primary regional endpoint"
    region = record["region"]
    return {
        "agent_action": (
            f"Confirm to the customer that identity verification succeeded for {customer_id} "
            f"via the {route_note} ({region}) and ask how you can help with their account."
        )
    }
