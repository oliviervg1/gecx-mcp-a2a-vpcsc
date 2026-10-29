# CXAS runtime globals: CallbackContext, LlmRequest, LlmResponse and Part are injected by the sandbox (no imports).
# ruff: noqa: F821
"""before_model_callback: hides end_session, transfer_to_agent, and any returned controller tools."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Hide end_session, transfer_to_agent, and any controller tool that just returned on this turn.

    Args:
        callback_context: Runtime callback context with session state.
        llm_request: Outgoing LLM request configuration and conversation contents.

    Returns:
        None so the model proceeds with its post-tool spoken response.
    """
    try:
        llm_request.config.hide_tool("end_session")
        llm_request.config.hide_tool("transfer_to_agent")
        for tool_name in _returned_tool_names(llm_request):
            llm_request.config.hide_tool(tool_name)
        return None
    except Exception:
        logger.exception("hide_system_tools callback failed")
        return None


def _returned_tool_names(llm_request: Any) -> list[str]:
    """Return the names of the tools whose function responses form the latest content turn."""
    if not llm_request.contents:
        return []
    last_parts = llm_request.contents[-1].parts
    if not last_parts:
        return []
    return [
        p.function_response.name
        for p in last_parts
        if p.function_response and p.function_response.name
    ]
