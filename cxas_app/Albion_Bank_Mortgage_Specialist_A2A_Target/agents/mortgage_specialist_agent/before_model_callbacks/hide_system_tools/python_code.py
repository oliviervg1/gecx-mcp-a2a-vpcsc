# CXAS runtime globals: CallbackContext, LlmRequest, LlmResponse and Part are injected by the sandbox (no imports).
# ruff: noqa: F821
"""before_model_callback: hides end_session from the LLM so session lifecycle stays under callback control."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Hide end_session from the model on every pass.

    Args:
        callback_context: Runtime callback context with session state.
        llm_request: Outgoing LLM request.

    Returns:
        None so the model proceeds with normal tool execution.
    """
    try:
        llm_request.config.hide_tool("end_session")
        return None
    except Exception:
        logger.exception("hide_system_tools callback failed")
        return None
