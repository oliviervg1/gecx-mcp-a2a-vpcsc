#!/usr/bin/env python3
"""Phase A verification script: MCP Error Handling, Regional Failover & A2A Baseline.

Executes five automated verification tests against a target GCP project prior to VPC-SC enforcement:
- Test 1A: Unpinned MCP toolset attached directly to a sub-agent (reproduces 400 FAILED_PRECONDITION).
- Test 1B-i: Python Function Tool controller wrapping an unpinned primary MCP toolset (/mcp1/) with automatic failover to secondary (/mcp2/).
- Test 1B-ii: Python Function Tool controller after sending a toolOverrides snapshot PATCH on the primary MCP toolset (/mcp1/) with automatic failover to secondary (/mcp2/).
- Test 1B-iii: Python Function Tool controller when both primary and secondary MCP toolsets return HTTP 400 (/mcp1/), verifying graceful degradation.
- Test 2-0: Baseline CXAS-to-CXAS A2A call via RemoteAgentTool prior to VPC-SC perimeter enforcement.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request
import uuid


def get_access_token(account: str = "") -> str:
    """Retrieves an OAuth 2.0 access token from the active gcloud session."""
    cmd = ["gcloud", "auth", "print-access-token"]
    if account:
        cmd.append(f"--account={account}")
    return subprocess.check_output(cmd, text=True).strip()


class CxasTestClient:
    """Lightweight REST client for provisioning and testing CXAS applications."""

    def __init__(self, project_id: str, location: str, account: str = "") -> None:
        self.project_id = project_id
        self.location = location
        self.account = account
        self.base_url = f"https://ces.googleapis.com/v1beta/projects/{project_id}/locations/{location}"

    def request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        expect_error: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        """Sends an authenticated HTTP request to the CXAS REST API."""
        token = get_access_token(self.account)
        headers = {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": self.project_id,
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"raw_error": raw}
            if not expect_error:
                print(
                    f"[HTTP {err.code}] {method} {url} -> {json.dumps(parsed, indent=2)}",
                    file=sys.stderr,
                )
            return err.code, parsed

    def wait_lro(self, operation: dict[str, Any]) -> dict[str, Any]:
        """Polls a long-running operation until completion."""
        if operation.get("done"):
            return operation.get("response", operation)
        if "name" not in operation:
            raise RuntimeError(f"Unexpected operation response: {json.dumps(operation)}")
        op_name = operation["name"]
        url = f"https://ces.googleapis.com/v1beta/{op_name}"
        for _ in range(60):
            time.sleep(2)
            status, data = self.request("GET", url)
            if status == 200 and data.get("done"):
                if "error" in data:
                    raise RuntimeError(f"Operation failed: {json.dumps(data['error'])}")
                return data.get("response", data)
        raise TimeoutError(f"Timed out waiting for operation {op_name}")

    def ensure_app(self, app_id: str, display_name: str) -> str:
        """Creates a CXAS application if it does not already exist."""
        app_url = f"{self.base_url}/apps/{app_id}"
        status, data = self.request("GET", app_url, expect_error=True)
        if status == 200:
            return data["name"]
        post_status, op = self.request(
            "POST",
            f"{self.base_url}/apps?appId={app_id}",
            {
                "displayName": display_name,
                "timeZoneSettings": {"timeZone": "Europe/London"},
                "variableDeclarations": [
                    {
                        "name": "idv_status",
                        "description": "Customer identity verification status.",
                        "schema": {"type": "STRING"},
                    },
                    {
                        "name": "idv_region",
                        "description": "Region that fulfilled customer verification.",
                        "schema": {"type": "STRING"},
                    },
                    {
                        "name": "escalation_reason",
                        "description": "Structured escalation or completion reason code.",
                        "schema": {"type": "STRING"},
                    },
                    {
                        "name": "call_complete",
                        "description": "Lifecycle flag set when the call should end.",
                        "schema": {"type": "STRING"},
                    },
                ],
            },
        )
        if post_status not in (200, 201):
            raise RuntimeError(
                f"Failed to create CXAS app {app_id} (HTTP {post_status}): {json.dumps(op)}"
            )
        res = self.wait_lro(op)
        return res["name"]

    def upsert_toolset(self, app_id: str, toolset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Creates or updates an MCP toolset resource."""
        ts_url = f"{self.base_url}/apps/{app_id}/toolsets/{toolset_id}"
        status, _ = self.request("GET", ts_url, expect_error=True)
        if status == 200:
            st, result = self.request("PATCH", f"{ts_url}?updateMask=displayName,mcpToolset", body)
        else:
            st, result = self.request(
                "POST", f"{self.base_url}/apps/{app_id}/toolsets?toolsetId={toolset_id}", body
            )
        if st not in (200, 201):
            raise RuntimeError(f"Failed to upsert toolset {toolset_id} (HTTP {st}): {json.dumps(result)}")
        return result

    def upsert_tool(
        self, app_id: str, tool_id: str, body: dict[str, Any], update_mask: str
    ) -> dict[str, Any]:
        """Creates or updates a CXAS tool resource."""
        t_url = f"{self.base_url}/apps/{app_id}/tools/{tool_id}"
        status, _ = self.request("GET", t_url, expect_error=True)
        if status == 200:
            st, result = self.request("PATCH", f"{t_url}?updateMask={update_mask}", body)
        else:
            st, result = self.request(
                "POST", f"{self.base_url}/apps/{app_id}/tools?toolId={tool_id}", body
            )
        if st not in (200, 201):
            raise RuntimeError(f"Failed to upsert tool {tool_id} (HTTP {st}): {json.dumps(result)}")
        return result

    def upsert_agent(
        self, app_id: str, agent_id: str, body: dict[str, Any], update_mask: str
    ) -> dict[str, Any]:
        """Creates or updates a CXAS agent resource."""
        a_url = f"{self.base_url}/apps/{app_id}/agents/{agent_id}"
        status, _ = self.request("GET", a_url, expect_error=True)
        if status == 200:
            st, result = self.request("PATCH", f"{a_url}?updateMask={update_mask}", body)
        else:
            st, result = self.request(
                "POST", f"{self.base_url}/apps/{app_id}/agents?agentId={agent_id}", body
            )
        if st not in (200, 201):
            raise RuntimeError(f"Failed to upsert agent {agent_id} (HTTP {st}): {json.dumps(result)}")
        return result

    def set_root_agent(self, app_id: str, agent_name: str) -> None:
        """Sets the root agent on a CXAS application."""
        st, result = self.request(
            "PATCH",
            f"{self.base_url}/apps/{app_id}?updateMask=rootAgent",
            {"rootAgent": agent_name},
        )
        if st not in (200, 201):
            raise RuntimeError(f"Failed to set rootAgent on {app_id} (HTTP {st}): {json.dumps(result)}")

    def run_session(
        self, app_id: str, text: str, session_id: str | None = None
    ) -> tuple[int, dict[str, Any], str]:
        """Executes a single conversational turn against a CXAS application."""
        if not session_id:
            session_id = f"sess-{uuid.uuid4().hex[:10]}"
        session_name = (
            f"projects/{self.project_id}/locations/{self.location}/apps/{app_id}/sessions/{session_id}"
        )
        url = f"{self.base_url}/apps/{app_id}/sessions/{session_id}:runSession"
        body = {
            "config": {"session": session_name},
            "inputs": [{"text": text}],
        }
        status, resp = self.request("POST", url, body, expect_error=True)
        return status, resp, session_id


def build_a2a_tool_body(
    project_id: str,
    location: str,
    mortgage_app_id: str,
    custom_sa: str | None = None,
) -> dict[str, Any]:
    """Builds the RemoteAgentTool configuration payload for CXAS-to-CXAS A2A calls."""
    remote_tool: dict[str, Any] = {
        "name": "mortgage_specialist",
        "description": "Delegates mortgage rate and overpayment questions to the Mortgage Specialist CXAS app.",
        "agentCard": {
            "name": "mortgage_specialist",
            "description": "Answers Albion Bank mortgage rate and overpayment inquiries.",
            "version": "1.0.0",
            "supportedInterfaces": [
                {
                    "url": f"https://ces.googleapis.com/v1/projects/{project_id}/locations/{location}/apps/{mortgage_app_id}",
                    "protocolBinding": "HTTP+JSON",
                    "protocolVersion": "1.0",
                }
            ],
            "skills": [
                {
                    "id": "mortgage_rates",
                    "name": "mortgage_rates",
                    "description": "Mortgage rates and overpayment rules.",
                    "tags": ["mortgage"],
                }
            ],
        },
    }
    if custom_sa:
        remote_tool["apiAuthentication"] = {
            "serviceAccountAuthConfig": {
                "serviceAccount": custom_sa,
            }
        }
    return {"remoteAgentTool": remote_tool}


def run_phase_a(client: CxasTestClient, mcp_url: str, output_file: str) -> dict[str, Any]:
    """Executes Phase A verification tests (1A, 1B-i, 1B-ii, 1B-iii, and 2-0)."""
    results: dict[str, Any] = {}
    app_id = "scenario1-mcp-repro"
    print(f"=== Provisioning {app_id} ===")
    client.ensure_app(app_id, "Albion Bank MCP Failover Test App")

    snapshot_override = [
        {
            "tool": "verify_customer",
            "snapshot": {
                "description": "Verifies a banking customer's identity status by customer ID.",
                "inputSchema": {
                    "type": "OBJECT",
                    "properties": {"customer_id": {"type": "STRING"}},
                    "required": ["customer_id"],
                },
            },
        }
    ]

    # 1. Create the primary (unhealthy /mcp1/) and secondary (healthy /mcp2/) MCP toolsets
    client.upsert_toolset(
        app_id,
        "customer_idv",
        {
            "displayName": "customer_idv",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp1/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
            },
        },
    )
    client.upsert_toolset(
        app_id,
        "customer_idv_primary",
        {
            "displayName": "customer_idv_primary",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp1/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
            },
        },
    )
    client.upsert_toolset(
        app_id,
        "customer_idv_secondary",
        {
            "displayName": "customer_idv_secondary",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp2/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
                "toolOverrides": snapshot_override,
            },
        },
    )

    # 2. Test 1A: Unpinned MCP toolset attached directly to idv_sub_agent
    print("\n=== Test 1A: Unpinned Agent-Attached MCP Toolset (Expect 400 FAILED_PRECONDITION on Turn 2) ===")
    idv_broken = client.upsert_agent(
        app_id,
        "idv_sub_agent",
        {
            "displayName": "idv_sub_agent",
            "instruction": "You are the IDV sub-agent. Verify the customer using customer_idv.",
            "toolsets": [
                {
                    "toolset": f"projects/{client.project_id}/locations/{client.location}/apps/{app_id}/toolsets/customer_idv",
                    "toolIds": ["verify_customer"],
                }
            ],
            "tools": [],
        },
        "displayName,instruction,toolsets,tools",
    )
    root_steering = client.upsert_agent(
        app_id,
        "steering_root_agent",
        {
            "displayName": "Personal_Banking_Steering_Agent",
            "instruction": (
                "You are the Albion Bank Personal Banking Steering Agent. "
                "When the customer asks to check their credit card balance or verify their identity, "
                "immediately transfer to idv_sub_agent."
            ),
            "childAgents": [idv_broken["name"]],
        },
        "displayName,instruction,childAgents",
    )
    client.set_root_agent(app_id, root_steering["name"])

    s1a_id = f"s1a-{uuid.uuid4().hex[:8]}"
    st1, _, _ = client.run_session(app_id, "hi", session_id=s1a_id)
    st2, r2, _ = client.run_session(app_id, "check my credit card balance", session_id=s1a_id)
    print(f"Test 1A -> Turn 1 HTTP {st1}, Turn 2 HTTP {st2}")
    print(json.dumps(r2, indent=2))
    results["test_1A"] = {"turn1_status": st1, "turn2_status": st2, "turn2_response": r2}

    # 3. Detach MCP toolset from sub-agent and attach the Python failover controller tool
    print("\n=== Configuring Python Controller Tool for Tests 1B-i, 1B-ii, and 1B-iii ===")
    repo_root = Path(__file__).resolve().parent.parent
    python_code = (
        repo_root / "tools" / "verify_customer_identity" / "python_function" / "python_code.py"
    ).read_text(encoding="utf-8")

    ctrl_tool = client.upsert_tool(
        app_id,
        "verify_customer_identity",
        {
            "pythonFunction": {
                "name": "verify_customer_identity",
                "pythonCode": python_code,
            }
        },
        "pythonFunction",
    )
    client.upsert_agent(
        app_id,
        "idv_sub_agent",
        {
            "displayName": "idv_sub_agent",
            "instruction": (
                "You are the Albion Bank IDV sub-agent. Call verify_customer_identity with the "
                "customer_id provided by the caller and follow its agent_action instruction."
            ),
            "tools": [ctrl_tool["name"]],
            "toolsets": [],
        },
        "displayName,instruction,tools,toolsets",
    )
    print("Waiting 65s for agent definition cache refresh...")
    time.sleep(65)

    print("\n=== Test 1B-i: Python Controller with Unpinned Primary MCP Failover (/mcp1/ -> /mcp2/) ===")
    st_1bi, r_1bi, _ = client.run_session(
        app_id,
        "Please check my credit card balance and verify my customer ID CUST-101.",
    )
    print(f"Test 1B-i -> HTTP {st_1bi}")
    print(json.dumps(r_1bi, indent=2))
    results["test_1Bi"] = {"status": st_1bi, "response": r_1bi}

    # Patch toolOverrides on customer_idv_primary and inspect whether snapshot persisted on GET
    print("\n=== Test 1B-ii: Python Controller with toolOverrides Patch on Primary MCP (/mcp1/ -> /mcp2/) ===")
    patched_primary = client.upsert_toolset(
        app_id,
        "customer_idv_primary",
        {
            "displayName": "customer_idv_primary",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp1/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
                "toolOverrides": snapshot_override,
            },
        },
    )
    overrides = patched_primary.get("mcpToolset", {}).get("toolOverrides", [])
    snapshot_persisted = bool(overrides and overrides[0].get("snapshot"))
    print(f"Primary toolset snapshot persisted via REST PATCH: {snapshot_persisted}")
    print("Waiting 65s for toolset definition cache refresh...")
    time.sleep(65)
    st_1bii, r_1bii, _ = client.run_session(
        app_id,
        "Please check my credit card balance and verify my customer ID CUST-202.",
    )
    print(f"Test 1B-ii -> HTTP {st_1bii}")
    print(json.dumps(r_1bii, indent=2))
    results["test_1Bii"] = {
        "status": st_1bii,
        "snapshot_persisted_via_rest": snapshot_persisted,
        "response": r_1bii,
    }

    # Point customer_idv_secondary to broken /mcp1/ as well to test total regional outage (Test 1B-iii)
    print("\n=== Test 1B-iii: Python Controller Graceful Degradation When Both Regions Fail (/mcp1/ + /mcp1/) ===")
    client.upsert_toolset(
        app_id,
        "customer_idv_secondary",
        {
            "displayName": "customer_idv_secondary",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp1/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
                "toolOverrides": snapshot_override,
            },
        },
    )
    print("Waiting 65s for toolset definition cache refresh...")
    time.sleep(65)
    st_1biii, r_1biii, _ = client.run_session(
        app_id,
        "Please check my credit card balance and verify my customer ID CUST-999.",
    )
    print(f"Test 1B-iii -> HTTP {st_1biii}")
    print(json.dumps(r_1biii, indent=2))
    results["test_1Biii"] = {"status": st_1biii, "response": r_1biii}

    # Restore customer_idv_secondary to healthy /mcp2/
    client.upsert_toolset(
        app_id,
        "customer_idv_secondary",
        {
            "displayName": "customer_idv_secondary",
            "mcpToolset": {
                "serverAddress": f"{mcp_url}/mcp2/",
                "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
                "toolOverrides": snapshot_override,
            },
        },
    )

    # 4. Provision Scenario 2 Apps and run Test 2-0 (A2A Baseline without VPC-SC)
    print("\n=== Test 2-0: CXAS-to-CXAS A2A Baseline (Prior to VPC-SC Perimeter) ===")
    mortgage_app_id = "mortgage-specialist-app"
    caller_app_id = "personal-banking-a2a-caller"
    client.ensure_app(mortgage_app_id, "Albion Bank Mortgage Specialist App")
    client.ensure_app(caller_app_id, "Albion Bank Personal Banking A2A Caller App")

    mortgage_root = client.upsert_agent(
        mortgage_app_id,
        "mortgage_root_agent",
        {
            "displayName": "Mortgage_Specialist_Root_Agent",
            "instruction": (
                "You are the Albion Bank Mortgage Specialist Agent. "
                "When asked about mortgage rates or overpayment rules, state that the 5-year fixed rate is 4.15% "
                "and customers may overpay up to 10% of their outstanding balance per calendar year penalty-free."
            ),
        },
        "displayName,instruction",
    )
    client.set_root_agent(mortgage_app_id, mortgage_root["name"])

    a2a_tool = client.upsert_tool(
        caller_app_id,
        "mortgage_specialist",
        build_a2a_tool_body(client.project_id, client.location, mortgage_app_id, custom_sa=None),
        "remoteAgentTool",
    )
    caller_root = client.upsert_agent(
        caller_app_id,
        "caller_root_agent",
        {
            "displayName": "Personal_Banking_Steering_A2A_Caller",
            "instruction": (
                "You are the Albion Bank Personal Banking Steering Agent. "
                "Whenever the user asks a mortgage question, call the mortgage_specialist tool immediately "
                "and relay its response."
            ),
            "tools": [a2a_tool["name"]],
        },
        "displayName,instruction,tools",
    )
    client.set_root_agent(caller_app_id, caller_root["name"])

    st_20, r_20, _ = client.run_session(
        caller_app_id,
        "What is the 5-year fixed mortgage rate and the annual overpayment allowance?",
    )
    print(f"Test 2-0 -> HTTP {st_20}")
    print(json.dumps(r_20, indent=2))
    results["test_2_0"] = {"status": st_20, "response": r_20}

    Path(output_file).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved Phase A results to {output_file}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase A MCP failover and A2A baseline verification tests."
    )
    parser.add_argument("--project-id", required=True, help="Target GCP project ID")
    parser.add_argument("--location", default="eu", help="CXAS region (default: eu)")
    parser.add_argument("--mcp-url", required=True, help="Deployed Cloud Run FastMCP base URL")
    parser.add_argument("--account", default="", help="Optional gcloud account email")
    parser.add_argument(
        "--output", default="phase_a_results.json", help="Output JSON path for test results"
    )
    args = parser.parse_args()

    client = CxasTestClient(args.project_id, args.location, args.account)
    run_phase_a(client, args.mcp_url.rstrip("/"), args.output)


if __name__ == "__main__":
    main()
