"""Offline unit tests for the verify_customer_identity Python Function Tool controller."""

import builtins
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


class FakeExternalResponse:
    """Simulates the CXAS Python runtime ExternalResponse object."""

    def __init__(self, status_code: int, ok: bool, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.ok = ok
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> dict[str, Any]:
        return json.loads(self.text) if self.text else {}


class FakeContext:
    """Simulates the injected CXAS session context object."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {}


class FakeToolsNamespace:
    """Simulates the injected CXAS tools namespace."""

    def __init__(self, primary_fn: Any, secondary_fn: Any) -> None:
        self.customer_idv_primary_verify_customer = primary_fn
        self.customer_idv_secondary_verify_customer = secondary_fn


def _load_tool_module(
    monkeypatch: pytest.MonkeyPatch,
    context_obj: FakeContext,
    tools_obj: FakeToolsNamespace,
) -> Any:
    monkeypatch.setattr(builtins, "context", context_obj, raising=False)
    monkeypatch.setattr(builtins, "tools", tools_obj, raising=False)
    tool_path = (
        Path(__file__).resolve().parent.parent
        / "tools"
        / "verify_customer_identity"
        / "python_function"
        / "python_code.py"
    )
    spec = importlib.util.spec_from_file_location("verify_customer_identity_tool", tool_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_customer_id_prompts_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()
    tools_ns = FakeToolsNamespace(
        primary_fn=lambda _: FakeExternalResponse(200, True),
        secondary_fn=lambda _: FakeExternalResponse(200, True),
    )
    mod = _load_tool_module(monkeypatch, ctx, tools_ns)

    res = mod.verify_customer_identity("")
    assert list(res.keys()) == ["agent_action"]
    assert "provide their customer ID" in res["agent_action"]


def test_primary_success_does_not_call_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()
    secondary_called = False

    def primary_fn(args: dict[str, str]) -> FakeExternalResponse:
        return FakeExternalResponse(
            0,
            True,
            {
                "text_output": [
                    {
                        "status": "VERIFIED",
                        "customer_id": args["customer_id"],
                        "region": "europe-west2-primary",
                    }
                ]
            },
        )

    def secondary_fn(_: dict[str, str]) -> FakeExternalResponse:
        nonlocal secondary_called
        secondary_called = True
        return FakeExternalResponse(500, False)

    mod = _load_tool_module(monkeypatch, ctx, FakeToolsNamespace(primary_fn, secondary_fn))
    res = mod.verify_customer_identity("CUST-101")

    assert not secondary_called
    assert ctx.state["idv_status"] == "VERIFIED"
    assert ctx.state["idv_region"] == "europe-west2-primary"
    assert "primary regional endpoint (europe-west2-primary)" in res["agent_action"]


def test_stage1_http_400_fails_over_to_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()

    def primary_fn(_: dict[str, str]) -> FakeExternalResponse:
        # Simulates HTTP 400 Bad Request during MCP session initialization
        return FakeExternalResponse(400, False, None)

    def secondary_fn(args: dict[str, str]) -> FakeExternalResponse:
        return FakeExternalResponse(
            0,
            True,
            {
                "text_output": [
                    {
                        "status": "VERIFIED",
                        "customer_id": args["customer_id"],
                        "region": "europe-west1-secondary",
                    }
                ]
            },
        )

    mod = _load_tool_module(monkeypatch, ctx, FakeToolsNamespace(primary_fn, secondary_fn))
    res = mod.verify_customer_identity("CUST-101")

    assert ctx.state["idv_status"] == "VERIFIED"
    assert ctx.state["idv_region"] == "europe-west1-secondary"
    assert "secondary regional failover (europe-west1-secondary)" in res["agent_action"]


def test_stage2_error_envelope_fails_over_to_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()

    def primary_fn(_: dict[str, str]) -> FakeExternalResponse:
        # Simulates status_code=0, ok=True with {"status": "error"} payload
        return FakeExternalResponse(
            0,
            True,
            {"status": "error", "error": "Failed to initialize MCP session"},
        )

    def secondary_fn(args: dict[str, str]) -> FakeExternalResponse:
        return FakeExternalResponse(
            0,
            True,
            {
                "text_output": [
                    {
                        "status": "VERIFIED",
                        "customer_id": args["customer_id"],
                        "region": "europe-west1-secondary",
                    }
                ]
            },
        )

    mod = _load_tool_module(monkeypatch, ctx, FakeToolsNamespace(primary_fn, secondary_fn))
    res = mod.verify_customer_identity("CUST-202")

    assert ctx.state["idv_status"] == "VERIFIED"
    assert ctx.state["idv_region"] == "europe-west1-secondary"
    assert "CUST-202" in res["agent_action"]


def test_unexpected_200_envelope_missing_text_output_fails_over_to_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = FakeContext()

    def primary_fn(_: dict[str, str]) -> FakeExternalResponse:
        # Simulates unexpected 200 payload missing text_output
        return FakeExternalResponse(0, True, {"unexpected": "shape"})

    def secondary_fn(args: dict[str, str]) -> FakeExternalResponse:
        return FakeExternalResponse(
            0,
            True,
            {
                "text_output": [
                    {
                        "status": "VERIFIED",
                        "customer_id": args["customer_id"],
                        "region": "europe-west1-secondary",
                    }
                ]
            },
        )

    mod = _load_tool_module(monkeypatch, ctx, FakeToolsNamespace(primary_fn, secondary_fn))
    res = mod.verify_customer_identity("CUST-303")

    assert ctx.state["idv_status"] == "VERIFIED"
    assert ctx.state["idv_region"] == "europe-west1-secondary"
    assert "CUST-303" in res["agent_action"]


def test_both_regions_down_returns_graceful_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()
    tools_ns = FakeToolsNamespace(
        primary_fn=lambda _: FakeExternalResponse(400, False, None),
        secondary_fn=lambda _: FakeExternalResponse(503, False, None),
    )
    mod = _load_tool_module(monkeypatch, ctx, tools_ns)
    res = mod.verify_customer_identity("CUST-999")

    assert ctx.state["idv_status"] == "UNAVAILABLE"
    assert ctx.state["escalation_reason"] == "IDV_REGIONS_UNAVAILABLE"
    assert ctx.state["call_complete"] == "true"
    assert "temporarily unavailable" in res["agent_action"]
    assert "banking specialist will assist them shortly" in res["agent_action"]
    assert "transfer" not in res["agent_action"].lower()
