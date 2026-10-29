# CXAS runtime globals: CallbackContext, LlmRequest, LlmResponse and Part are injected by the sandbox (no imports).
# ruff: noqa: F821
"""Router-only before_model_callback: delivers a deterministic greeting on Turn 1."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

GREETING_TEXT = (
    "Welcome to Albion Bank Personal Banking. I am Clara, your digital banking assistant. "
    "How can I help you today?"
)


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Emit the opening greeting on the first turn without waiting for an LLM pass.

    Args:
        callback_context: Runtime callback context with session state.
        llm_request: Outgoing LLM request.

    Returns:
        LlmResponse containing the greeting on Turn 1, or None on subsequent turns.
    """
    try:
        if callback_context.state.get("session_greeted"):
            return None

        callback_context.state["session_greeted"] = True
        callback_context.state["last_agent_action"] = GREETING_TEXT
        return LlmResponse.from_parts(parts=[Part.from_text(text=GREETING_TEXT)])
    except Exception:
        logger.exception("session_greeting callback failed")
        return None
