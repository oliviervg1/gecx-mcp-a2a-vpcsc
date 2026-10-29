# CX Agent Studio (GECX) Application Bundles (`cxas-scrapi` Format)

This directory contains three complete CX Agent Studio (GECX) application bundles structured in the standard [`cxas-scrapi`](https://github.com/GoogleCloudPlatform/cxas-scrapi) layout (`app.json`, `global_instruction.txt`, `environment.json`, `agents/`, `tools/`, and `toolsets/`) so you can lint, push, and pull them directly with the `cxas` CLI.

---

## Application Bundles Overview

| Application Bundle | Scenario | Root Agent & Sub-Agents | Tools & Toolsets |
| :--- | :--- | :--- | :--- |
| **[`Albion_Bank_MCP_Failover/`](Albion_Bank_MCP_Failover/)** | Scenario 1: Resilient Regional MCP Failover | `steering_agent` → `idv_sub_agent` (silent post-tool transfer in `before_model_callback`) | **Tools:** [`route_to_idv`](Albion_Bank_MCP_Failover/tools/route_to_idv/python_function/python_code.py), [`verify_customer_identity`](Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py)<br/>**Toolsets:** [`customer_idv_primary`](Albion_Bank_MCP_Failover/toolsets/customer_idv_primary/customer_idv_primary.json) (`/mcp1/`), [`customer_idv_secondary`](Albion_Bank_MCP_Failover/toolsets/customer_idv_secondary/customer_idv_secondary.json) (`/mcp2/`) |
| **[`Albion_Bank_Personal_Banking_A2A_Caller/`](Albion_Bank_Personal_Banking_A2A_Caller/)** | Scenario 2: A2A Caller Application | `personal_banking_agent` | **Tool:** [`mortgage_specialist`](Albion_Bank_Personal_Banking_A2A_Caller/tools/mortgage_specialist/mortgage_specialist.json) (`RemoteAgentTool` invoking the remote Mortgage Specialist CXAS app over `HTTP+JSON`) |
| **[`Albion_Bank_Mortgage_Specialist_A2A_Target/`](Albion_Bank_Mortgage_Specialist_A2A_Target/)** | Scenario 2: A2A Target Application | `mortgage_specialist_agent` | **Tool:** [`lookup_mortgage_rates`](Albion_Bank_Mortgage_Specialist_A2A_Target/tools/lookup_mortgage_rates/python_function/python_code.py) (returns 2-year `4.45%` and 5-year `4.15%` fixed rates and `10%` annual overpayment allowance) |

---

## Key Architectural Patterns Demonstrated

1. **Decoupled MCP Toolsets with Python Controller Failover (`Albion_Bank_MCP_Failover`):**
   - `idv_sub_agent.json` sets `"toolsets": []` so CXAS never executes an unhandled entry-time MCP `initialize` or `tools/list` call during turn preprocessing.
   - Instead, `idv_sub_agent` calls [`verify_customer_identity`](Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py), which invokes `tools.customer_idv_primary_verify_customer` first and automatically fails over to `tools.customer_idv_secondary_verify_customer` when `/mcp1/` returns an HTTP error (`not resp.ok`) or a call-time MCP error envelope (`body.get("status") == "error"`).
   - Both MCP toolsets ([`customer_idv_primary.json`](Albion_Bank_MCP_Failover/toolsets/customer_idv_primary/customer_idv_primary.json) and [`customer_idv_secondary.json`](Albion_Bank_MCP_Failover/toolsets/customer_idv_secondary/customer_idv_secondary.json)) include a concrete `mcpToolset.toolOverrides` configuration (`tool: "verify_customer"`, `descriptionOverride`, and `snapshot.inputSchema`) alongside deterministic `toolFakeConfig` Python blocks (`tool_fake_config/code_block/python_code.py`) so you can test primary failure and secondary failover in the CXAS Simulator with **"Use mock tool responses"** enabled before deploying Cloud Run. Note that in the public CXAS v1beta API, `McpToolOverride.snapshot` is annotated `Output only` and is populated server-side when pinning schemas in the CXAS Console (it is included locally for `cxas lint` schema validation and exported bundle fidelity).
2. **Silent State-Driven Sub-Agent Transfers in `before_model_callback`:**
   - When `route_to_idv` sets `context.state["target_agent"] = "idv_sub_agent"`, the `agent_transfer` `before_model_callback` intercepts the post-tool pass (`_is_tool_response(llm_request) == True`), pops `target_agent`, and returns `Part.from_agent_transfer(agent="idv_sub_agent")` immediately—saving a redundant post-tool LLM pass and preventing `unexpected_function_call` errors.
3. **A2A `RemoteAgentTool` & VPC-SC Custom Service Account Authentication (`Albion_Bank_Personal_Banking_A2A_Caller`):**
   - [`tools/mortgage_specialist/mortgage_specialist.json`](Albion_Bank_Personal_Banking_A2A_Caller/tools/mortgage_specialist/mortgage_specialist.json) defines the A2A `agentCard` (`protocolBinding: "HTTP+JSON"`, `protocolVersion: "1.0"`).
   - Both [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](../scripts/run_phase_a_mcp_and_a2a_baseline.py) and [`scripts/run_phase_b_vpcsc_a2a.py`](../scripts/run_phase_b_vpcsc_a2a.py) push these application bundles directly using `cxas_scrapi.core.apps.Apps.import_app(..., conflict_strategy="OVERWRITE")` for Pattern 3A (same-perimeter default Service Agent), and for Pattern 3B (cross-perimeter custom caller Service Account `a2a-custom-caller@YOUR_PROJECT_ID.iam.gserviceaccount.com`) resolve the imported `mortgage_specialist` tool resource name via `Tools.list_tools()` and apply `remoteAgentTool.apiAuthentication.serviceAccountAuthConfig.serviceAccount` via `AuthorizedSession` (since the client `google.cloud.ces_v1beta.types.RemoteAgentTool` descriptor omits `api_authentication`).

---

## Linting, Pushing & Pulling with `cxas-scrapi`

### 1. Lint All Three Applications Offline

```bash
for app in Albion_Bank_MCP_Failover Albion_Bank_Personal_Banking_A2A_Caller Albion_Bank_Mortgage_Specialist_A2A_Target; do
  cxas lint --app-dir "cxas_app/${app}"
done
```

### 2. Configure Endpoint URLs & Push to Your GCP Project

1. **Push the A2A Target App First (`Albion_Bank_Mortgage_Specialist_A2A_Target`):**
   Always pass `--display-name` (or `--to <APP_RESOURCE_NAME> --overwrite` when updating an existing app) so `cxas push` sets a clear application display name:
   ```bash
   cxas push \
     --app-dir cxas_app/Albion_Bank_Mortgage_Specialist_A2A_Target \
     --project-id "${PROJECT_ID}" \
     --location eu \
     --display-name "Albion_Bank_Mortgage_Specialist_A2A_Target"
   ```
   Copy the created `<TARGET_APP_ID>` from the `cxas push` output and substitute `YOUR_PROJECT_ID` and `mortgage-specialist-app` in [`Albion_Bank_Personal_Banking_A2A_Caller/tools/mortgage_specialist/mortgage_specialist.json`](Albion_Bank_Personal_Banking_A2A_Caller/tools/mortgage_specialist/mortgage_specialist.json) with `${PROJECT_ID}` and `<TARGET_APP_ID>`.

2. **Push the A2A Caller App (`Albion_Bank_Personal_Banking_A2A_Caller`):**
   ```bash
   cxas push \
     --app-dir cxas_app/Albion_Bank_Personal_Banking_A2A_Caller \
     --project-id "${PROJECT_ID}" \
     --location eu \
     --display-name "Albion_Bank_Personal_Banking_A2A_Caller"
   ```

3. **Update MCP Endpoint URLs & Push the MCP Failover App (`Albion_Bank_MCP_Failover`):**
   Replace `https://YOUR_PRIMARY_MCP_URL` and `https://YOUR_SECONDARY_MCP_URL` in [`customer_idv_primary.json`](Albion_Bank_MCP_Failover/toolsets/customer_idv_primary/customer_idv_primary.json), [`customer_idv_secondary.json`](Albion_Bank_MCP_Failover/toolsets/customer_idv_secondary/customer_idv_secondary.json), and [`Albion_Bank_MCP_Failover/environment.json`](Albion_Bank_MCP_Failover/environment.json) with the Cloud Run `MCP_URL` printed by `./scripts/deploy_mcp_server.sh`, then push:
   ```bash
   cxas push \
     --app-dir cxas_app/Albion_Bank_MCP_Failover \
     --project-id "${PROJECT_ID}" \
     --location eu \
     --display-name "Albion_Bank_MCP_Failover"
   ```

   To overwrite an existing deployed application in place, pass `--to` and `--overwrite`:
   ```bash
   cxas push \
     --app-dir cxas_app/Albion_Bank_MCP_Failover \
     --to "projects/${PROJECT_ID}/locations/eu/apps/${APP_ID}" \
     --overwrite
   ```

### 3. Pull an Existing Application Bundle with `cxas pull`

```bash
cxas pull \
  --from "projects/${PROJECT_ID}/locations/eu/apps/${APP_ID}" \
  --app-dir cxas_app/Albion_Bank_MCP_Failover \
  --overwrite
```
