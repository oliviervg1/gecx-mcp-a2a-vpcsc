# CXAS runtime globals: CallbackContext, LlmRequest, LlmResponse and Part are injected by the sandbox (no imports).
# ruff: noqa: F821
"""after_model_callback: terminates or escalates the session when call_complete == 'true'."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """Append Part.from_end_session and latch call_complete = 'released'.

    Args:
        callback_context: Runtime callback context with session state.
        llm_response: Model response for the closing turn.

    Returns:
        LlmResponse with Part.from_end_session appended, or None if the call stays open.
    """
    try:
        state = callback_context.state
        parts = llm_response.content.parts if llm_response.content else []

        if any(p.function_call for p in parts):
            return None
        if state.get("call_complete") != "true":
            return None

        state["call_complete"] = "released"
        reason = state.get("escalation_reason") or "CALL_COMPLETED"
        escalated = reason != "CALL_COMPLETED"
        text_parts = [p for p in parts if p.text]
        return LlmResponse.from_parts(
            parts=text_parts + [Part.from_end_session(reason=reason, escalated=escalated)]
        )
    except Exception:
        logger.exception("release_line callback failed")
        return None
