# Controller tool for mortgage_specialist_agent: returns Albion Bank mortgage rates and overpayment policy.
# CXAS runtime globals: `context` (session state) is injected by the sandbox (no imports).
# ruff: noqa: F821

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

_FIXED_RATES = {
    "2": "4.45%",
    "5": "4.15%",
}
_ANNUAL_OVERPAYMENT_ALLOWANCE = "10%"


def lookup_mortgage_rates(
    term_years: Literal["", "2", "5"] = "",
) -> dict[str, Any]:
    """Look up Albion Bank fixed mortgage interest rates and the annual penalty-free overpayment allowance.

    Args:
        term_years: Optional fixed-rate term in years ("2" or "5"). Defaults to "5" when omitted.

    Returns:
        Dictionary with agent_action containing the verified mortgage rate and overpayment policy.
    """
    try:
        selected_term = term_years if term_years in _FIXED_RATES else "5"
        rate = _FIXED_RATES[selected_term]
        action = (
            f"State that Albion Bank's {selected_term}-year fixed mortgage rate is {rate} "
            f"and customers may overpay up to {_ANNUAL_OVERPAYMENT_ALLOWANCE} of their outstanding "
            "balance per calendar year penalty-free."
        )
        return {"agent_action": action}
    except Exception:
        logger.exception("lookup_mortgage_rates failed")
        return {
            "agent_action": (
                "Apologize that mortgage rate details are temporarily unavailable and let the "
                "customer know a mortgage specialist will assist them shortly."
            )
        }
