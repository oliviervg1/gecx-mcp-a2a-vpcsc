# Controller tool for steering_agent: classifies the customer's request and stages silent sub-agent routing.
# CXAS runtime globals: `context` (session state) is injected by the sandbox (no imports).
# ruff: noqa: F821

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)


def route_to_idv(
    request_type: Literal["", "VERIFY_IDENTITY", "HUMAN_SPECIALIST"] = "",
) -> dict[str, Any]:
    """Classify the customer's personal banking request and route to identity verification.

    Call this tool whenever the customer asks to verify their identity, check their
    credit card balance, or speak with a human banking specialist.

    Args:
        request_type: "VERIFY_IDENTITY" for balance checks or identity verification, or "HUMAN_SPECIALIST" when the customer asks for a person.

    Returns:
        Dictionary with agent_action guiding the model's spoken response.
    """
    try:
        state = context.state

        # Step 1: Handle human specialist requests deterministically.
        if request_type == "HUMAN_SPECIALIST":
            state["escalation_reason"] = "CALLER_REQUESTED_HUMAN"
            state["call_complete"] = "true"
            return {
                "agent_action": "Let the customer know a general Albion Bank specialist will assist them shortly."
            }

        # Step 2: Stage silent sub-agent routing to idv_sub_agent for identity verification.
        if request_type == "VERIFY_IDENTITY":
            state["target_agent"] = "idv_sub_agent"
            return {
                "agent_action": "Ask the customer to provide their customer ID so you can verify their identity."
            }

        # Step 3: Prompt the customer to state how we can help if the request was unclear.
        return {
            "agent_action": "Ask the customer how you can help with their personal banking account today."
        }
    except Exception:
        logger.exception("route_to_idv failed")
        context.state["escalation_reason"] = "ROUTER_SYSTEM_ERROR"
        context.state["call_complete"] = "true"
        return {
            "agent_action": (
                "Apologize that you cannot complete this request automatically and let the customer "
                "know a general Albion Bank specialist will assist them shortly."
            )
        }
