# Changelog

All notable changes to the Albion Bank CX Agent Studio (GECX) MCP Regional Failover and A2A VPC-SC Verification Suite are documented in this file.

## [0.1.0] - 2026-10-29

### Added — MCP Regional Failover Reference Implementation & Verification (`1A`, `1B-i`, `1B-ii`, `1B-iii`)

- **Why:** Attaching an MCP toolset directly to a CXAS sub-agent causes the runtime to execute a live JSON-RPC `initialize` and `tools/list` handshake during turn preprocessing before any callbacks or tool wrappers run. If the primary regional proxy or MCP server returns HTTP 400 or becomes unreachable, the turn crashes immediately with an unhandled `400 FAILED_PRECONDITION` error.
- **Fix:** Added [`mcp_server/main.py`](mcp_server/main.py) (dual-route FastMCP server exposing `/mcp1` returning HTTP 400 and `/mcp2` serving `verify_customer`) and [`tools/verify_customer_identity/python_function/python_code.py`](tools/verify_customer_identity/python_function/python_code.py), which omits MCP toolsets from the sub-agent's `toolsets` array and invokes them inside a Python Function Tool controller that fails over automatically from `customer_idv_primary` to `customer_idv_secondary` (or degrades gracefully when both regions fail).
- **Test:** Verified offline in [`tests/test_verify_customer_identity.py`](tests/test_verify_customer_identity.py) and [`tests/test_mcp_server.py`](tests/test_mcp_server.py), and live against the CXAS v1beta API via [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](scripts/run_phase_a_mcp_and_a2a_baseline.py).
- **Docs:** Documented in [`docs/guides/mcp_and_a2a_technical_guide.md`](docs/guides/mcp_and_a2a_technical_guide.md), [`docs/tools/README.md`](docs/tools/README.md), and [`docs/tools/verify_customer_identity.md`](docs/tools/verify_customer_identity.md).

### Added — A2A Protocol VPC Service Controls Policy Templates & Live Verification (`2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, `2C`)

- **Why:** Native CXAS-to-CXAS A2A calls (`lf.a2a.v1.A2AService.SendMessage`) route from Google's managed CXAS runtime environment to the public `ces.googleapis.com` API endpoint rather than through a customer VPC Service Directory. In VPC Service Controls policy audit logs (`cloudaudit.googleapis.com/policy`), `A2AService.SendMessage` is evaluated from the calling Service Account's project container (`source: projects/<PROJECT_NUMBER>`) without a target project resource container, blocking even same-project A2A calls with `RESOURCES_NOT_IN_SAME_SERVICE_PERIMETER` unless an egress policy permits `resources: ["*"]` on `ces.googleapis.com`.
- **Fix:** Added [`vpcsc_policies/egress_a2a_cxas.yaml`](vpcsc_policies/egress_a2a_cxas.yaml) (`resources: ["*"]` on `ces.googleapis.com`) and [`vpcsc_policies/ingress_a2a_cxas.yaml`](vpcsc_policies/ingress_a2a_cxas.yaml), alongside [`scripts/run_phase_b_vpcsc_a2a.py`](scripts/run_phase_b_vpcsc_a2a.py) to verify default Service Agent and custom Service Account authentication (`roles/iam.serviceAccountTokenCreator` and `roles/ces.client`) inside an enforced VPC-SC service perimeter.
- **Test:** Verified across all 6 A2A test stages (`2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, `2C`) via [`scripts/run_phase_a_mcp_and_a2a_baseline.py`](scripts/run_phase_a_mcp_and_a2a_baseline.py) and [`scripts/run_phase_b_vpcsc_a2a.py`](scripts/run_phase_b_vpcsc_a2a.py).
- **Docs:** Documented in [`docs/guides/mcp_and_a2a_technical_guide.md`](docs/guides/mcp_and_a2a_technical_guide.md) and [`docs/architecture/end_to_end_verification_walkthrough.md`](docs/architecture/end_to_end_verification_walkthrough.md).
