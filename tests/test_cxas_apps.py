"""Offline unit tests for the cxas-scrapi application bundles under cxas_app/."""

import builtins
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CXAS_APP_DIR = REPO_ROOT / "cxas_app"
APP_NAMES = [
    "Albion_Bank_MCP_Failover",
    "Albion_Bank_Personal_Banking_A2A_Caller",
    "Albion_Bank_Mortgage_Specialist_A2A_Target",
]
FORBIDDEN_TRANSFER_WORDS = ("transfer", "handoff", "connecting")


class FakePart:
    """Simulates the CXAS runtime Part object."""

    def __init__(
        self,
        text: str | None = None,
        function_call: Any = None,
        function_response: Any = None,
        agent_transfer: str | None = None,
        end_session: dict[str, Any] | None = None,
    ) -> None:
        self.text = text
        self.function_call = function_call
        self.function_response = function_response
        self.agent_transfer = agent_transfer
        self.end_session = end_session

    @classmethod
    def from_text(cls, text: str) -> "FakePart":
        return cls(text=text)

    @classmethod
    def from_agent_transfer(cls, agent: str) -> "FakePart":
        return cls(agent_transfer=agent)

    @classmethod
    def from_end_session(cls, reason: str = "", escalated: bool = False) -> "FakePart":
        return cls(end_session={"reason": reason, "escalated": escalated})


class FakeLlmResponse:
    """Simulates the CXAS runtime LlmResponse object."""

    def __init__(self, parts: list[FakePart]) -> None:
        self.content = SimpleNamespace(parts=parts)

    @classmethod
    def from_parts(cls, parts: list[FakePart]) -> "FakeLlmResponse":
        return cls(parts=parts)


def _load_py(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, Any] | None = None,
) -> tuple[ModuleType, SimpleNamespace]:
    ctx = SimpleNamespace(state=state if state is not None else {}, agent_name="steering_agent")
    monkeypatch.setattr(builtins, "context", ctx, raising=False)
    monkeypatch.setattr(builtins, "CallbackContext", Any, raising=False)
    monkeypatch.setattr(builtins, "LlmRequest", Any, raising=False)
    monkeypatch.setattr(builtins, "LlmResponse", FakeLlmResponse, raising=False)
    monkeypatch.setattr(builtins, "Part", FakePart, raising=False)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, ctx


@pytest.mark.parametrize("app_name", APP_NAMES)
def test_cxas_app_structure_and_schema_invariants(app_name: str) -> None:
    """Verifies app.json, environment.json, agent configs, childAgents tree, and instructions."""
    app_root = CXAS_APP_DIR / app_name
    app_json = json.loads((app_root / "app.json").read_text(encoding="utf-8"))
    assert app_json["name"] == app_name

    global_inst_path = app_root / app_json["globalInstruction"]
    assert global_inst_path.exists()
    global_inst_text = global_inst_path.read_text(encoding="utf-8")
    for required_tag in ("<role>", "<persona>", "<taskflow>"):
        assert required_tag in global_inst_text, f"{global_inst_path} missing {required_tag}"
    for forbidden in FORBIDDEN_TRANSFER_WORDS:
        assert forbidden not in global_inst_text.lower(), f"{global_inst_path} mentions '{forbidden}'"

    env_text = (app_root / "environment.json").read_text(encoding="utf-8")
    env_json = json.loads(env_text)
    assert isinstance(env_json, dict)
    assert '"dev"' not in env_text and '"prod"' not in env_text

    for var in app_json.get("variableDeclarations", []):
        assert "required" in var["schema"], f"Missing required: [] on variable {var['name']}"

    agents_dir = app_root / "agents"
    root_agent = app_json["rootAgent"]
    assert (agents_dir / root_agent / f"{root_agent}.json").exists()

    parents_by_child: dict[str, list[str]] = {}
    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        cfg = json.loads((agent_dir / f"{agent_dir.name}.json").read_text(encoding="utf-8"))
        inst_path = app_root / cfg["instruction"]
        assert inst_path.exists()
        inst_text = inst_path.read_text(encoding="utf-8")
        for required_tag in ("<role>", "<persona>", "<constraints>", "<taskflow>", "<examples>"):
            assert required_tag in inst_text, f"{inst_path} missing {required_tag}"
        for forbidden in FORBIDDEN_TRANSFER_WORDS:
            assert forbidden not in inst_text.lower(), f"{inst_path} mentions '{forbidden}'"

        for child in cfg.get("childAgents", []):
            parents_by_child.setdefault(child, []).append(agent_dir.name)

    for child, parents in parents_by_child.items():
        assert len(parents) == 1, f"Sub-agent {child} has multiple parents: {parents}"

    for tool_py in (app_root / "tools").rglob("python_code.py"):
        tool_source = tool_py.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_TRANSFER_WORDS:
            assert forbidden not in tool_source, f"{tool_py} mentions '{forbidden}'"


def test_idv_sub_agent_before_model_hides_end_session_and_returned_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies idv_sub_agent before_model_callback hides end_session and returned tools."""
    app_root = CXAS_APP_DIR / "Albion_Bank_MCP_Failover"
    cb_mod, ctx = _load_py(
        app_root
        / "agents"
        / "idv_sub_agent"
        / "before_model_callbacks"
        / "agent_transfer"
        / "python_code.py",
        monkeypatch,
    )
    hidden_tools: list[str] = []
    tool_req = SimpleNamespace(
        config=SimpleNamespace(hide_tool=lambda name: hidden_tools.append(name)),
        contents=[
            SimpleNamespace(
                parts=[
                    FakePart(
                        function_response=SimpleNamespace(name="verify_customer_identity"),
                    )
                ]
            )
        ],
    )
    assert cb_mod.before_model_callback(ctx, tool_req) is None
    assert hidden_tools == ["end_session", "verify_customer_identity"]


def test_route_to_idv_and_silent_before_model_transfer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies route_to_idv stages target_agent and agent_transfer emits Part.from_agent_transfer."""
    app_root = CXAS_APP_DIR / "Albion_Bank_MCP_Failover"
    route_mod, ctx = _load_py(
        app_root / "tools" / "route_to_idv" / "python_function" / "python_code.py",
        monkeypatch,
    )
    res = route_mod.route_to_idv(request_type="VERIFY_IDENTITY")
    assert ctx.state["target_agent"] == "idv_sub_agent"
    assert "provide their customer ID" in res["agent_action"]

    cb_mod, _ = _load_py(
        app_root
        / "agents"
        / "steering_agent"
        / "before_model_callbacks"
        / "agent_transfer"
        / "python_code.py",
        monkeypatch,
        state=ctx.state,
    )
    hidden_tools: list[str] = []

    # Non-tool pass should NOT emit Part.from_agent_transfer even when target_agent is set.
    non_tool_req = SimpleNamespace(
        config=SimpleNamespace(hide_tool=lambda name: hidden_tools.append(name)),
        contents=[SimpleNamespace(parts=[FakePart(text="check my balance")])],
    )
    assert cb_mod.before_model_callback(ctx, non_tool_req) is None
    assert ctx.state["target_agent"] == "idv_sub_agent"

    # Post-tool pass SHOULD emit Part.from_agent_transfer and clear target_agent.
    tool_req = SimpleNamespace(
        config=SimpleNamespace(hide_tool=lambda name: hidden_tools.append(name)),
        contents=[
            SimpleNamespace(
                parts=[
                    FakePart(
                        function_response=SimpleNamespace(name="route_to_idv"),
                    )
                ]
            )
        ],
    )
    cb_resp = cb_mod.before_model_callback(ctx, tool_req)
    assert cb_resp is not None
    assert cb_resp.content.parts[0].agent_transfer == "idv_sub_agent"
    assert ctx.state["target_agent"] == ""
    assert "route_to_idv" in hidden_tools


def test_human_specialist_session_greeting_and_release_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies HUMAN_SPECIALIST escalation, session_greeting, and release_line callbacks."""
    app_root = CXAS_APP_DIR / "Albion_Bank_MCP_Failover"
    route_mod, ctx = _load_py(
        app_root / "tools" / "route_to_idv" / "python_function" / "python_code.py",
        monkeypatch,
    )
    res = route_mod.route_to_idv(request_type="HUMAN_SPECIALIST")
    assert ctx.state["escalation_reason"] == "CALLER_REQUESTED_HUMAN"
    assert ctx.state["call_complete"] == "true"
    assert "specialist will assist them shortly" in res["agent_action"]

    greet_mod, greet_ctx = _load_py(
        app_root
        / "agents"
        / "steering_agent"
        / "before_model_callbacks"
        / "session_greeting"
        / "python_code.py",
        monkeypatch,
    )
    empty_req = SimpleNamespace(contents=[SimpleNamespace(parts=[FakePart(text="")])])
    greet_resp = greet_mod.before_model_callback(greet_ctx, empty_req)
    assert greet_resp is not None
    assert "Albion Bank" in greet_resp.content.parts[0].text
    assert greet_ctx.state["session_greeted"] is True
    assert greet_mod.before_model_callback(greet_ctx, empty_req) is None

    rel_mod, rel_ctx = _load_py(
        app_root
        / "agents"
        / "steering_agent"
        / "after_model_callbacks"
        / "release_line"
        / "python_code.py",
        monkeypatch,
        state=ctx.state,
    )
    llm_resp = FakeLlmResponse(parts=[FakePart.from_text("A specialist will assist you shortly.")])
    rel_out = rel_mod.after_model_callback(rel_ctx, llm_resp)
    assert rel_out is not None
    assert rel_out.content.parts[-1].end_session == {
        "reason": "CALLER_REQUESTED_HUMAN",
        "escalated": True,
    }
    assert rel_ctx.state["call_complete"] == "released"


def test_lookup_mortgage_rates_and_toolset_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies lookup_mortgage_rates and the primary/secondary MCP toolset fakes."""
    rates_mod, _ = _load_py(
        CXAS_APP_DIR
        / "Albion_Bank_Mortgage_Specialist_A2A_Target"
        / "tools"
        / "lookup_mortgage_rates"
        / "python_function"
        / "python_code.py",
        monkeypatch,
    )
    five_yr = rates_mod.lookup_mortgage_rates("5")
    assert "4.15%" in five_yr["agent_action"]
    assert "10%" in five_yr["agent_action"]

    primary_fake, _ = _load_py(
        CXAS_APP_DIR
        / "Albion_Bank_MCP_Failover"
        / "toolsets"
        / "customer_idv_primary"
        / "tool_fake_config"
        / "code_block"
        / "python_code.py",
        monkeypatch,
    )
    assert primary_fake.fake_tool_call(None, {"customer_id": "CUST-101"}, None)["status"] == "error"

    secondary_fake, _ = _load_py(
        CXAS_APP_DIR
        / "Albion_Bank_MCP_Failover"
        / "toolsets"
        / "customer_idv_secondary"
        / "tool_fake_config"
        / "code_block"
        / "python_code.py",
        monkeypatch,
    )
    sec_ok = secondary_fake.fake_tool_call(None, {"customer_id": "CUST-101"}, None)
    assert sec_ok["text_output"][0]["region"] == "europe-west1-secondary"
