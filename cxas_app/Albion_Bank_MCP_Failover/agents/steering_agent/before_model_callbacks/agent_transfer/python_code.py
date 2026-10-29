# CXAS runtime globals: CallbackContext, LlmRequest, LlmResponse and Part are injected by the sandbox (no imports).
# ruff: noqa: F821
"""before_model_callback: hides system tools and executes silent sub-agent transfers on post-tool passes."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Hide system tools and execute silent Part.from_agent_transfer when target_agent is staged.

    Args:
        callback_context: Runtime callback context with session state and agent_name.
        llm_request: Outgoing LLM request configuration and conversation contents.

    Returns:
        LlmResponse containing Part.from_agent_transfer on a post-tool pass, or None.
    """
    try:
        state = callback_context.state
        is_tool_response = _is_tool_response(llm_request)

        # Step 1: Hide system tools and any controller tool that just returned on this turn.
        llm_request.config.hide_tool("end_session")
        llm_request.config.hide_tool("transfer_to_agent")
        for tool_name in _returned_tool_names(llm_request):
            llm_request.config.hide_tool(tool_name)

        # Step 2: Execute silent sub-agent transfer when a controller tool staged target_agent.
        target = state.get("target_agent")
        if target and is_tool_response:
            state["target_agent"] = ""
            if target != callback_context.agent_name:
                return LlmResponse.from_parts(parts=[Part.from_agent_transfer(agent=target)])

        return None
    except Exception:
        logger.exception("agent_transfer callback failed")
        return None


def _is_tool_response(llm_request: Any) -> bool:
    """Return True when the latest content turn is a tool function response."""
    if not llm_request.contents:
        return False
    last_parts = llm_request.contents[-1].parts
    return bool(last_parts and last_parts[-1].function_response)


def _returned_tool_names(llm_request: Any) -> list[str]:
    """Return the names of the tools whose function responses form the latest content turn."""
    if not _is_tool_response(llm_request):
        return []
    return [
        p.function_response.name
        for p in llm_request.contents[-1].parts
        if p.function_response and p.function_response.name
    ]
