# Changelog

All notable changes to the Albion Bank CX Agent Studio (GECX) MCP Regional Failover and A2A VPC-SC Verification Suite are documented in this file.

## [0.3.0] - 2026-10-29

### Added — Concrete MCP `toolOverrides` Schema Snapshot Example in `cxas_app/`

- **Why:** Provide a concrete, `cxas lint`-validated (`google.cloud.ces_v1beta.types.Toolset.from_json`) example of `mcpToolset.toolOverrides` (`tool`, `descriptionOverride`, and `snapshot.inputSchema`) directly inside the `cxas-scrapi` application bundle.
- **Fix:** Added `toolOverrides` for `verify_customer` to [`cxas_app/Albion_Bank_MCP_Failover/toolsets/customer_idv_primary/customer_idv_primary.json`](cxas_app/Albion_Bank_MCP_Failover/toolsets/customer_idv_primary/customer_idv_primary.json) and [`cxas_app/Albion_Bank_MCP_Failover/toolsets/customer_idv_secondary/customer_idv_secondary.json`](cxas_app/Albion_Bank_MCP_Failover/toolsets/customer_idv_secondary/customer_idv_secondary.json) (noting that `McpToolOverride.snapshot` is `Output only` on `v1beta` and populated server-side when pinning in the CXAS Console), and added schema/callback path assertions in [`tests/test_cxas_apps.py`](tests/test_cxas_apps.py).

### Changed — Refactored Verification Scripts (`scripts/`) to Use `cxas-scrapi` & Aligned A2A `end_session` Handling

- **Why:** Replace raw `urllib.request` / `curl` REST provisioning in the verification and teardown scripts with the `cxas-scrapi` SDK (`Apps`, `Agents`, `Tools`, `Sessions`, and `AgentServiceClient`), and align `global_instruction.txt` with `instruction.txt` across the A2A apps.
- **Fix:** Refactored [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](scripts/run_phase_a_mcp_and_a2a_baseline.py), [`scripts/run_phase_b_vpcsc_a2a.py`](scripts/run_phase_b_vpcsc_a2a.py), and [`scripts/teardown.sh`](scripts/teardown.sh) to stage and import the `cxas_app/` bundles via `Apps.import_app(..., conflict_strategy="OVERWRITE")` (validating `ImportAppResponse.warnings` and disabling `toolFakeConfig.enableFakeMode` for live Cloud Run verification), resolve server-assigned agent/tool/toolset resource names via `Agents.get_agents_map(reverse=True)` and `Tools.list_tools()`, mutate agents/toolsets via `Agents.update_agent` and `Tools.update_tool`, apply and verify custom Service Account `apiAuthentication` on `RemoteAgentTool` via `AuthorizedSession`, update `SecuritySettings` via `AgentServiceClient.update_security_settings`, and execute conversational turns via `Sessions.run`. Renamed `idv_sub_agent`'s `before_model_callback` from `agent_transfer` to `hide_system_tools` (hiding both `end_session` and `transfer_to_agent`), and updated the A2A applications to invoke `{@TOOL: end_session}` after the caller confirms they have no further questions.
- **Test:** Verified all three apps pass `cxas lint` with 0 errors and 0 warnings, and all 18 offline unit tests pass in `pytest` (live cloud traces in `docs/architecture/end_to_end_verification_walkthrough.md` were captured with v0.2.0; the v0.3.0 `cxas-scrapi` script harness is unit-tested offline via `pytest` and ready for live cloud re-execution).
- **Docs:** Updated [`README.md`](README.md), [`cxas_app/README.md`](cxas_app/README.md), [`docs/README.md`](docs/README.md), [`docs/guides/mcp_and_a2a_technical_guide.md`](docs/guides/mcp_and_a2a_technical_guide.md), [`docs/architecture/end_to_end_verification_walkthrough.md`](docs/architecture/end_to_end_verification_walkthrough.md), [`docs/tools/README.md`](docs/tools/README.md), and [`docs/tools/verify_customer_identity.md`](docs/tools/verify_customer_identity.md).

### Removed — Duplicate Root `tools/` Directory, Unreachable Callbacks & Write-Only `last_agent_action` State Variable

- **Why:** Eliminate duplicated tool source files, unreachable callback paths, and write-only state variables across the repository.
- **Fix:** Removed the standalone duplicate `tools/verify_customer_identity/` directory at the repository root (consolidating on [`cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py`](cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py)), removed unreachable `release_line` / `hide_system_tools` callbacks and unused `call_complete` / `escalation_reason` state variables from the two A2A applications, removed the unreachable `target_agent` transfer branch from `idv_sub_agent`, and removed the write-only `last_agent_action` state variable across all three applications.

## [0.2.0] - 2026-10-29

### Added — Complete `cxas-scrapi`-Compatible Application Bundles (`cxas_app/`)

- **Why:** Provide complete, `cxas lint`-validated CX Agent Studio application bundles in the standard `cxas-scrapi` format (`app.json`, `global_instruction.txt`, `environment.json`, `agents/`, `tools/`, and `toolsets/`) so engineers can inspect, lint (`cxas lint`), push (`cxas push`), and pull (`cxas pull`) the agents directly alongside the automated verification scripts.
- **Fix:** Added [`cxas_app/Albion_Bank_MCP_Failover/`](cxas_app/Albion_Bank_MCP_Failover/), [`cxas_app/Albion_Bank_Personal_Banking_A2A_Caller/`](cxas_app/Albion_Bank_Personal_Banking_A2A_Caller/), and [`cxas_app/Albion_Bank_Mortgage_Specialist_A2A_Target/`](cxas_app/Albion_Bank_Mortgage_Specialist_A2A_Target/), plus [`cxaslint.yaml`](cxaslint.yaml) and [`cxas_app/README.md`](cxas_app/README.md).
- **Test:** Verified all three application bundles pass `cxas lint` with 0 errors and 0 warnings, and added [`tests/test_cxas_apps.py`](tests/test_cxas_apps.py) (`17 passed` across `pytest`).
- **Docs:** Updated [`README.md`](README.md), [`cxas_app/README.md`](cxas_app/README.md), [`docs/README.md`](docs/README.md), [`docs/tools/README.md`](docs/tools/README.md), and [`docs/tools/verify_customer_identity.md`](docs/tools/verify_customer_identity.md).

## [0.1.0] - 2026-10-29

### Added — MCP Regional Failover Reference Implementation & Verification (`1A`, `1B-i`, `1B-ii`, `1B-iii`)

- **Why:** Attaching an MCP toolset directly to a CXAS sub-agent causes the runtime to execute a live JSON-RPC `initialize` and `tools/list` handshake during turn preprocessing before any callbacks or tool wrappers run. If the primary regional proxy or MCP server returns HTTP 400 or becomes unreachable, the turn crashes immediately with an unhandled `400 FAILED_PRECONDITION` error.
- **Fix:** Added [`mcp_server/main.py`](mcp_server/main.py) (dual-route FastMCP server exposing `/mcp1` returning HTTP 400 and `/mcp2` serving `verify_customer`) and [`cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py`](cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py), which omits MCP toolsets from the sub-agent's `toolsets` array and invokes them inside a Python Function Tool controller that fails over automatically from `customer_idv_primary` to `customer_idv_secondary` (or degrades gracefully when both regions fail).
- **Test:** Verified offline in [`tests/test_verify_customer_identity.py`](tests/test_verify_customer_identity.py) and [`tests/test_mcp_server.py`](tests/test_mcp_server.py), and live against the CXAS v1beta API via [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](scripts/run_phase_a_mcp_and_a2a_baseline.py).
- **Docs:** Documented in [`docs/guides/mcp_and_a2a_technical_guide.md`](docs/guides/mcp_and_a2a_technical_guide.md), [`docs/tools/README.md`](docs/tools/README.md), and [`docs/tools/verify_customer_identity.md`](docs/tools/verify_customer_identity.md).

### Added — A2A Protocol VPC Service Controls Policy Templates & Live Verification (`2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, `2C`)

- **Why:** Native CXAS-to-CXAS A2A calls (`lf.a2a.v1.A2AService.SendMessage`) route from Google's managed CXAS runtime environment to the public `ces.googleapis.com` API endpoint rather than through a customer VPC Service Directory. In VPC Service Controls policy audit logs (`cloudaudit.googleapis.com/policy`), `A2AService.SendMessage` is evaluated from the calling Service Account's project container (`source: projects/<PROJECT_NUMBER>`) without a target project resource container, blocking even same-project A2A calls with `RESOURCES_NOT_IN_SAME_SERVICE_PERIMETER` unless an egress policy permits `resources: ["*"]` on `ces.googleapis.com`.
- **Fix:** Added [`vpcsc_policies/egress_a2a_cxas.yaml`](vpcsc_policies/egress_a2a_cxas.yaml) (`resources: ["*"]` on `ces.googleapis.com`) and [`vpcsc_policies/ingress_a2a_cxas.yaml`](vpcsc_policies/ingress_a2a_cxas.yaml), alongside [`scripts/run_phase_b_vpcsc_a2a.py`](scripts/run_phase_b_vpcsc_a2a.py) to verify default Service Agent and custom Service Account authentication (`roles/iam.serviceAccountTokenCreator` and `roles/ces.client`) inside an enforced VPC-SC service perimeter.
- **Test:** Verified across all 6 A2A test stages (`2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, `2C`) via [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](scripts/run_phase_a_mcp_and_a2a_baseline.py) and [`scripts/run_phase_b_vpcsc_a2a.py`](scripts/run_phase_b_vpcsc_a2a.py).
- **Docs:** Documented in [`docs/guides/mcp_and_a2a_technical_guide.md`](docs/guides/mcp_and_a2a_technical_guide.md) and [`docs/architecture/end_to_end_verification_walkthrough.md`](docs/architecture/end_to_end_verification_walkthrough.md).
