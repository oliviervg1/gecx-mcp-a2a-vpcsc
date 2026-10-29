#!/usr/bin/env python3
"""Phase A verification script: MCP Error Handling, Regional Failover & A2A Baseline.

Executes five automated verification tests against a target GCP project prior to VPC-SC enforcement
using the cxas-scrapi SDK (Apps, Agents, Tools, Sessions):
- Test 1A: Unpinned MCP toolset attached directly to a sub-agent (reproduces 400 FAILED_PRECONDITION).
- Test 1B-i: Python Function Tool controller wrapping an unpinned primary MCP toolset (/mcp1/) with automatic failover to secondary (/mcp2/).
- Test 1B-ii: Python Function Tool controller after updating toolOverrides on the primary MCP toolset (/mcp1/) via cxas-scrapi Tools.update_tool, with automatic failover to secondary (/mcp2/).
- Test 1B-iii: Python Function Tool controller when both primary and secondary MCP toolsets return HTTP 400 (/mcp1/), verifying graceful degradation.
- Test 2-0: Baseline CXAS-to-CXAS A2A call via RemoteAgentTool prior to VPC-SC perimeter enforcement.
"""

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Literal
import uuid

from cxas_scrapi.core.agents import Agents
from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.sessions import Sessions
from cxas_scrapi.core.tools import Tools
from google.api_core import exceptions as google_exceptions
from google.auth import credentials as auth_credentials
from google.auth.transport.requests import AuthorizedSession
from google.cloud.ces_v1beta import types
from google.protobuf import field_mask_pb2
from google.protobuf.json_format import MessageToDict

REPO_ROOT = Path(__file__).resolve().parent.parent

MCP_TOOL_OVERRIDES = [
    {
        "tool": "verify_customer",
        "descriptionOverride": "Verifies a banking customer's identity status by customer ID.",
        "snapshot": {
            "description": "Verifies a banking customer's identity status by customer ID.",
            "inputSchema": {
                "type": "OBJECT",
                "properties": {
                    "customer_id": {
                        "type": "STRING",
                        "description": "The customer identifier (for example, CUST-101).",
                    }
                },
                "required": ["customer_id"],
            },
        },
    }
]


class GcloudAccountCredentials(auth_credentials.Credentials):
    """Refreshes OAuth 2.0 bearer tokens from gcloud for an explicit --account."""

    def __init__(self, account: str, quota_project_id: str) -> None:
        super().__init__()
        self.account = account
        self._quota_project_id = quota_project_id
        self.refresh(None)

    def refresh(self, request: Any) -> None:
        cmd = ["gcloud", "auth", "print-access-token", f"--account={self.account}"]
        self.token = subprocess.check_output(cmd, text=True).strip()
        self.expiry = datetime.datetime.now(datetime.timezone.utc).replace(
            tzinfo=None
        ) + datetime.timedelta(minutes=55)


class CxasTestClient:
    """cxas-scrapi client wrapper for provisioning, mutating, and testing CXAS applications."""

    def __init__(self, project_id: str, location: str, account: str = "") -> None:
        self.project_id = project_id
        self.location = location
        self.account = account
        self.parent = f"projects/{project_id}/locations/{location}"
        creds = GcloudAccountCredentials(account, project_id) if account else None
        self.apps = Apps(project_id=project_id, location=location, creds=creds)

    def app_resource_name(self, app_id: str) -> str:
        """Returns the full CXAS resource name for an application ID."""
        return f"{self.parent}/apps/{app_id}"

    def ensure_app(self, app_id: str, display_name: str) -> str:
        """Returns the full resource name of an existing app, or creates it via cxas-scrapi Apps."""
        app_name = self.app_resource_name(app_id)
        try:
            app = self.apps.get_app(app_name)
            return app.name
        except google_exceptions.NotFound:
            app = self.apps.create_app(
                app_id=app_id,
                display_name=display_name,
                time_zone_settings=types.TimeZoneSettings(time_zone="Europe/London"),
            )
            return app.name

    def resolve_agent_name(self, app_id: str, display_name: str) -> str:
        """Resolves an agent display name to its server-assigned full resource name."""
        app_name = self.app_resource_name(app_id)
        agents_client = Agents(app_name=app_name, creds=self.apps.creds)
        agents_map = agents_client.get_agents_map(reverse=True)
        if display_name not in agents_map:
            raise KeyError(f"Agent '{display_name}' not found in {app_name}: {list(agents_map)}")
        return agents_map[display_name]

    def resolve_tool_name(self, app_id: str, display_name: str) -> str:
        """Resolves a tool display name (or system tool name) to its full resource name."""
        app_name = self.app_resource_name(app_id)
        tools_client = Tools(app_name=app_name, creds=self.apps.creds)
        for item in tools_client.list_tools():
            if "/tools/" not in item.name:
                continue
            if item.display_name == display_name or item.system_tool.name == display_name:
                return item.name

        if display_name in ("end_session", "set_session_variables"):
            req = types.ListToolsRequest(
                parent=app_name,
                filter="include_system_tools=true",
            )
            for item in tools_client.client.list_tools(request=req):
                if item.display_name == display_name or item.system_tool.name == display_name:
                    return item.name
            return f"{app_name}/tools/{display_name}"

        raise KeyError(f"Tool '{display_name}' not found in {app_name}")

    def resolve_toolset_name(self, app_id: str, display_name: str) -> str | None:
        """Resolves a toolset display name to its full resource name without calling retrieve_tools."""
        app_name = self.app_resource_name(app_id)
        tools_client = Tools(app_name=app_name, creds=self.apps.creds)
        for item in tools_client.list_tools():
            if "/toolsets/" in item.name and item.display_name == display_name:
                return item.name
        return None

    def set_remote_agent_custom_sa(
        self,
        app_id: str,
        tool_display_name: str,
        custom_sa: str,
    ) -> dict[str, Any]:
        """Applies serviceAccountAuthConfig on a RemoteAgentTool via AuthorizedSession and verifies persistence."""
        tool_name = self.resolve_tool_name(app_id, tool_display_name)
        url = f"https://ces.googleapis.com/v1beta/{tool_name}"
        authed_session = AuthorizedSession(self.apps.creds)
        headers = {"x-goog-user-project": self.project_id}

        get_resp = authed_session.get(url, headers=headers, timeout=60)
        get_resp.raise_for_status()
        current_tool = get_resp.json()
        remote_tool = current_tool.get("remoteAgentTool", {})
        remote_tool["apiAuthentication"] = {
            "serviceAccountAuthConfig": {"serviceAccount": custom_sa}
        }

        patch_resp = authed_session.patch(
            f"{url}?updateMask=remoteAgentTool",
            headers=headers,
            json={"remoteAgentTool": remote_tool},
            timeout=60,
        )
        patch_resp.raise_for_status()

        verify_resp = authed_session.get(url, headers=headers, timeout=60)
        verify_resp.raise_for_status()
        verified = verify_resp.json()
        persisted_sa = (
            verified.get("remoteAgentTool", {})
            .get("apiAuthentication", {})
            .get("serviceAccountAuthConfig", {})
            .get("serviceAccount")
        )
        if persisted_sa != custom_sa:
            raise RuntimeError(
                f"Expected custom Service Account '{custom_sa}' on {tool_name}, got '{persisted_sa}'"
            )
        return verified

    def push_app_bundle(
        self,
        app_id: str,
        bundle_name: str,
        replacements: dict[str, str] | None = None,
        custom_sa: str | None = None,
    ) -> str:
        """Stages a cxas_app/<bundle_name> directory and pushes it via Apps.import_app (OVERWRITE)."""
        src_dir = REPO_ROOT / "cxas_app" / bundle_name
        if not src_dir.is_dir():
            raise FileNotFoundError(f"CXAS app bundle not found: {src_dir}")

        app_name = self.ensure_app(app_id, display_name=bundle_name)
        subs = dict(replacements or {})
        subs.setdefault("YOUR_PROJECT_ID", self.project_id)
        subs.setdefault("YOUR_GCP_PROJECT_ID", self.project_id)
        subs.setdefault("/locations/eu/", f"/locations/{self.location}/")

        with tempfile.TemporaryDirectory() as tmp_root:
            staged_dir = Path(tmp_root) / "agent"
            shutil.copytree(src_dir, staged_dir)

            # Substitute environment-specific placeholders across all JSON resource files.
            for json_file in staged_dir.rglob("*.json"):
                text = json_file.read_text(encoding="utf-8")
                for old, new in subs.items():
                    text = text.replace(old, new)
                json_file.write_text(text, encoding="utf-8")

            # Disable toolFakeConfig.enableFakeMode when staging MCP toolsets for live Cloud Run verification.
            toolsets_dir = staged_dir / "toolsets"
            if toolsets_dir.exists():
                for ts_json in toolsets_dir.rglob("*.json"):
                    ts_payload = json.loads(ts_json.read_text(encoding="utf-8"))
                    if "toolFakeConfig" in ts_payload:
                        ts_payload["toolFakeConfig"]["enableFakeMode"] = False
                        ts_json.write_text(
                            json.dumps(ts_payload, indent=2) + "\n", encoding="utf-8"
                        )

            archive_base = str(Path(tmp_root) / "bundle")
            zip_path = shutil.make_archive(archive_base, "zip", root_dir=tmp_root, base_dir="agent")
            lro = self.apps.import_app(
                app_name=app_name,
                local_path=zip_path,
                conflict_strategy="OVERWRITE",
            )
            import_resp = lro.result()
            warnings = list(import_resp.warnings)
            if warnings:
                raise RuntimeError(
                    f"ImportApp reported validation warnings for {bundle_name}: {warnings}"
                )

        if custom_sa:
            self.set_remote_agent_custom_sa(app_id, "mortgage_specialist", custom_sa)
        return app_name

    def upsert_mcp_toolset(
        self,
        app_id: str,
        toolset_id: str,
        server_address: str,
        include_overrides: bool = True,
    ) -> types.Toolset:
        """Creates or updates an MCP toolset resource via cxas-scrapi Tools."""
        app_name = self.app_resource_name(app_id)
        tools_client = Tools(app_name=app_name, creds=self.apps.creds)
        existing_name = self.resolve_toolset_name(app_id, toolset_id)

        mcp_dict: dict[str, Any] = {
            "serverAddress": server_address,
            "apiAuthentication": {"serviceAgentIdTokenAuthConfig": {}},
        }
        if include_overrides:
            mcp_dict["toolOverrides"] = MCP_TOOL_OVERRIDES

        mcp_proto = types.McpToolset.from_json(json.dumps(mcp_dict))
        if existing_name:
            return tools_client.update_tool(
                existing_name,
                display_name=toolset_id,
                mcp_toolset=mcp_proto,
                tool_fake_config=types.ToolFakeConfig(enable_fake_mode=False),
            )
        return tools_client.create_tool(
            tool_id=toolset_id,
            display_name=toolset_id,
            payload=types.McpToolset.to_dict(mcp_proto),
            tool_type="mcp_toolset",
        )

    def configure_idv_agent_mode(
        self,
        app_id: str,
        mode: Literal["direct_mcp", "python_controller"],
        direct_toolset_id: str = "customer_idv",
    ) -> types.Agent:
        """Switches idv_sub_agent between direct MCP attachment (Test 1A) and Python controller (Tests 1B)."""
        app_name = self.app_resource_name(app_id)
        agents_client = Agents(app_name=app_name, creds=self.apps.creds)
        agent_name = self.resolve_agent_name(app_id, "idv_sub_agent")

        if mode == "direct_mcp":
            toolset_name = self.resolve_toolset_name(app_id, direct_toolset_id)
            if not toolset_name:
                raise KeyError(f"Toolset '{direct_toolset_id}' not found in {app_name}")
            return agents_client.update_agent(
                agent_name,
                toolsets=[
                    types.Agent.AgentToolset(
                        toolset=toolset_name,
                        tool_ids=["verify_customer"],
                    )
                ],
                tools=[],
            )

        verify_tool_name = self.resolve_tool_name(app_id, "verify_customer_identity")
        end_session_name = self.resolve_tool_name(app_id, "end_session")
        return agents_client.update_agent(
            agent_name,
            toolsets=[],
            tools=[verify_tool_name, end_session_name],
        )

    def update_security_settings(self, allowed_origins: list[str]) -> types.SecuritySettings:
        """Updates project-level CXAS SecuritySettings endpointControlPolicy via AgentServiceClient."""
        settings = types.SecuritySettings(
            name=f"{self.parent}/securitySettings",
            endpoint_control_policy=types.EndpointControlPolicy(
                enforcement_scope=types.EndpointControlPolicy.EnforcementScope.VPCSC_ONLY,
                allowed_origins=allowed_origins,
            ),
        )
        request = types.UpdateSecuritySettingsRequest(
            security_settings=settings,
            update_mask=field_mask_pb2.FieldMask(paths=["endpoint_control_policy"]),
        )
        return self.apps.client.update_security_settings(request=request)

    def run_session(
        self, app_id: str, text: str, session_id: str | None = None
    ) -> tuple[int, dict[str, Any], str]:
        """Executes a single conversational turn via cxas-scrapi Sessions.run."""
        if not session_id:
            session_id = f"sess-{uuid.uuid4().hex[:10]}"
        app_name = self.app_resource_name(app_id)
        sessions_client = Sessions(
            app_name=app_name,
            project_id=self.project_id,
            location=self.location,
            creds=self.apps.creds,
        )
        try:
            resp = sessions_client.run(session_id=session_id, text=text, modality="text")
            outputs_list = [
                types.SessionOutput.to_dict(out, preserving_proto_field_name=False)
                for out in resp.outputs
            ]
            raw_dict: dict[str, Any] = {
                "outputs": outputs_list,
                "structured": sessions_client.get_structured_response(resp),
            }
            return 200, raw_dict, session_id
        except google_exceptions.GoogleAPICallError as err:
            status_code = int(err.code) if err.code else 400
            error_payload = {
                "error": {
                    "code": status_code,
                    "message": err.message,
                    "status": str(err.grpc_status_code),
                }
            }
            return status_code, error_payload, session_id


def run_phase_a(client: CxasTestClient, mcp_url: str, output_file: str) -> dict[str, Any]:
    """Executes Phase A verification tests (1A, 1B-i, 1B-ii, 1B-iii, and 2-0) via cxas-scrapi."""
    results: dict[str, Any] = {}
    app_id = "scenario1-mcp-repro"
    print(f"=== Pushing Albion_Bank_MCP_Failover bundle to {app_id} via cxas-scrapi ===")
    client.push_app_bundle(
        app_id=app_id,
        bundle_name="Albion_Bank_MCP_Failover",
        replacements={
            "https://YOUR_PRIMARY_MCP_URL": mcp_url,
            "https://YOUR_SECONDARY_MCP_URL": mcp_url,
        },
    )

    # 1. Test 1A: Unpinned MCP toolset attached directly to idv_sub_agent
    print("\n=== Test 1A: Unpinned Agent-Attached MCP Toolset (Expect 400 FAILED_PRECONDITION on Turn 2) ===")
    client.upsert_mcp_toolset(
        app_id,
        "customer_idv",
        server_address=f"{mcp_url}/mcp1/",
        include_overrides=False,
    )
    client.configure_idv_agent_mode(app_id, mode="direct_mcp", direct_toolset_id="customer_idv")

    s1a_id = f"s1a-{uuid.uuid4().hex[:8]}"
    st1, _, _ = client.run_session(app_id, "hi", session_id=s1a_id)
    st2, r2, _ = client.run_session(app_id, "check my credit card balance", session_id=s1a_id)
    print(f"Test 1A -> Turn 1 HTTP {st1}, Turn 2 HTTP {st2}")
    print(json.dumps(r2, indent=2))
    results["test_1A"] = {"turn1_status": st1, "turn2_status": st2, "turn2_response": r2}

    # 2. Switch idv_sub_agent back to the Python failover controller tool via cxas-scrapi Agents
    print("\n=== Configuring Python Controller Tool via cxas-scrapi for Tests 1B-i, 1B-ii, and 1B-iii ===")
    client.configure_idv_agent_mode(app_id, mode="python_controller")
    client.upsert_mcp_toolset(
        app_id,
        "customer_idv_primary",
        server_address=f"{mcp_url}/mcp1/",
        include_overrides=False,
    )
    client.upsert_mcp_toolset(
        app_id,
        "customer_idv_secondary",
        server_address=f"{mcp_url}/mcp2/",
        include_overrides=True,
    )
    print("Waiting 65s for agent definition cache refresh...")
    time.sleep(65)

    print("\n=== Test 1B-i: Python Controller with Unpinned Primary MCP Failover (/mcp1/ -> /mcp2/) ===")
    s1bi_id = f"s1bi-{uuid.uuid4().hex[:8]}"
    client.run_session(app_id, "hi", session_id=s1bi_id)
    client.run_session(app_id, "Please check my credit card balance.", session_id=s1bi_id)
    st_1bi, r_1bi, _ = client.run_session(
        app_id,
        "My customer ID is CUST-101.",
        session_id=s1bi_id,
    )
    print(f"Test 1B-i -> HTTP {st_1bi}")
    print(json.dumps(r_1bi, indent=2))
    results["test_1Bi"] = {"status": st_1bi, "response": r_1bi}

    # 3. Update toolOverrides on customer_idv_primary via cxas-scrapi Tools.update_tool
    print("\n=== Test 1B-ii: Python Controller with toolOverrides on Primary MCP (/mcp1/ -> /mcp2/) ===")
    patched_primary = client.upsert_mcp_toolset(
        app_id,
        "customer_idv_primary",
        server_address=f"{mcp_url}/mcp1/",
        include_overrides=True,
    )
    patched_dict = MessageToDict(types.Toolset.pb(patched_primary))
    overrides = patched_dict.get("mcpToolset", {}).get("toolOverrides", [])
    snapshot_persisted = bool(overrides and overrides[0].get("snapshot"))
    print(f"Primary toolset snapshot persisted via Tools.update_tool: {snapshot_persisted}")
    print("Waiting 65s for toolset definition cache refresh...")
    time.sleep(65)

    s1bii_id = f"s1bii-{uuid.uuid4().hex[:8]}"
    client.run_session(app_id, "hi", session_id=s1bii_id)
    client.run_session(app_id, "Please check my credit card balance.", session_id=s1bii_id)
    st_1bii, r_1bii, _ = client.run_session(
        app_id,
        "My customer ID is CUST-202.",
        session_id=s1bii_id,
    )
    print(f"Test 1B-ii -> HTTP {st_1bii}")
    print(json.dumps(r_1bii, indent=2))
    results["test_1Bii"] = {
        "status": st_1bii,
        "snapshot_persisted_via_scrapi_update": snapshot_persisted,
        "response": r_1bii,
    }

    # 4. Point customer_idv_secondary to broken /mcp1/ via cxas-scrapi Tools.update_tool (Test 1B-iii)
    print("\n=== Test 1B-iii: Python Controller Graceful Degradation When Both Regions Fail (/mcp1/ + /mcp1/) ===")
    client.upsert_mcp_toolset(
        app_id,
        "customer_idv_secondary",
        server_address=f"{mcp_url}/mcp1/",
        include_overrides=True,
    )
    print("Waiting 65s for toolset definition cache refresh...")
    time.sleep(65)

    s1biii_id = f"s1biii-{uuid.uuid4().hex[:8]}"
    client.run_session(app_id, "hi", session_id=s1biii_id)
    client.run_session(app_id, "Please check my credit card balance.", session_id=s1biii_id)
    st_1biii, r_1biii, _ = client.run_session(
        app_id,
        "My customer ID is CUST-999.",
        session_id=s1biii_id,
    )
    print(f"Test 1B-iii -> HTTP {st_1biii}")
    print(json.dumps(r_1biii, indent=2))
    results["test_1Biii"] = {"status": st_1biii, "response": r_1biii}

    # Restore customer_idv_secondary to healthy /mcp2/
    client.upsert_mcp_toolset(
        app_id,
        "customer_idv_secondary",
        server_address=f"{mcp_url}/mcp2/",
        include_overrides=True,
    )

    # 5. Push Scenario 2 A2A Bundles via cxas-scrapi and run Test 2-0 (A2A Baseline without VPC-SC)
    print("\n=== Test 2-0: CXAS-to-CXAS A2A Baseline via cxas-scrapi (Prior to VPC-SC Perimeter) ===")
    mortgage_app_id = "mortgage-specialist-app"
    caller_app_id = "personal-banking-a2a-caller"

    client.push_app_bundle(
        app_id=mortgage_app_id,
        bundle_name="Albion_Bank_Mortgage_Specialist_A2A_Target",
    )
    client.push_app_bundle(
        app_id=caller_app_id,
        bundle_name="Albion_Bank_Personal_Banking_A2A_Caller",
        replacements={"apps/mortgage-specialist-app": f"apps/{mortgage_app_id}"},
        custom_sa=None,
    )

    s20_id = f"s20-{uuid.uuid4().hex[:8]}"
    client.run_session(caller_app_id, "hi", session_id=s20_id)
    st_20, r_20, _ = client.run_session(
        caller_app_id,
        "What is the 5-year fixed mortgage rate and the annual overpayment allowance?",
        session_id=s20_id,
    )
    print(f"Test 2-0 -> HTTP {st_20}")
    print(json.dumps(r_20, indent=2))
    results["test_2_0"] = {"status": st_20, "response": r_20}

    Path(output_file).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved Phase A results to {output_file}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase A MCP failover and A2A baseline verification tests via cxas-scrapi."
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
