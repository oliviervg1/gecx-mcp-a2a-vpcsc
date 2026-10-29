# Documentation Index — Albion Bank CXAS MCP & A2A Verification Suite

Welcome to the documentation hub for the Albion Bank CX Agent Studio (GECX) MCP Regional Failover and A2A VPC Service Controls reference repository.

---

## Navigation by Role

| Role | Recommended Reading Order |
| :--- | :--- |
| **Conversational AI Engineers** | 1. [Root Quickstart (`../README.md`)](../README.md)<br/>2. [CXAS Application Bundles Guide (`../cxas_app/README.md`)](../cxas_app/README.md)<br/>3. [MCP & A2A Technical Guide (`guides/mcp_and_a2a_technical_guide.md`)](guides/mcp_and_a2a_technical_guide.md)<br/>4. [Python Tool Catalog (`tools/README.md`)](tools/README.md) & [`verify_customer_identity.md`](tools/verify_customer_identity.md) |
| **Cloud Security & VPC-SC Architects** | 1. [Scenario 2 in the Technical Guide (`guides/mcp_and_a2a_technical_guide.md#3-scenario-2-a2a-connectivity--vpc-service-controls`)](guides/mcp_and_a2a_technical_guide.md#3-scenario-2-a2a-connectivity--vpc-service-controls)<br/>2. [End-to-End Verification Walkthrough (`architecture/end_to_end_verification_walkthrough.md`)](architecture/end_to_end_verification_walkthrough.md)<br/>3. [VPC-SC Policy Templates (`../vpcsc_policies/`)](../vpcsc_policies/) |
| **Platform & QA Engineers** | 1. [End-to-End Verification Walkthrough (`architecture/end_to_end_verification_walkthrough.md`)](architecture/end_to_end_verification_walkthrough.md)<br/>2. [Cloud Reproduction Scripts (`../scripts/`)](../scripts/)<br/>3. [Offline Unit Tests (`../tests/`)](../tests/) |

---

## Complete Document Index

### CX Agent Studio Application Bundles (`cxas-scrapi`)
- **[`../cxas_app/README.md`](../cxas_app/README.md)** — Guide to the three `cxas-scrapi`-compatible application bundles (`Albion_Bank_MCP_Failover`, `Albion_Bank_Personal_Banking_A2A_Caller`, and `Albion_Bank_Mortgage_Specialist_A2A_Target`), including `cxas lint`, `cxas push`, and `cxas pull` commands.

### Guides
- **[`guides/mcp_and_a2a_technical_guide.md`](guides/mcp_and_a2a_technical_guide.md)** — Explains why unpinned MCP toolsets fail during turn preprocessing before callbacks run, how to combine `toolOverrides` snapshots with a Python Function Tool controller for regional failover, where to place load balancer vs. application failover, and how to configure VPC Service Controls (`egressPolicies` with `resources: ["*"]` and `ingressPolicies`) and IAM (`roles/ces.client`) for native A2A calls.

### Architecture & Live Verification
- **[`architecture/end_to_end_verification_walkthrough.md`](architecture/end_to_end_verification_walkthrough.md)** — Detailed walkthrough of all 10 live verification test cases (`1A`, `1B-i`, `1B-ii`, `1B-iii`, `2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, and `2C`), showing the exact CXAS API configurations, observed HTTP responses, and Cloud Audit Log `egressViolations` payloads.

### Tools
- **[`tools/README.md`](tools/README.md)** — Overview of the Python controller tool pattern in CXAS, execution flow diagram, and line-numbered index into [`../cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py`](../cxas_app/Albion_Bank_MCP_Failover/tools/verify_customer_identity/python_function/python_code.py), `route_to_idv`, and `lookup_mortgage_rates`.
- **[`tools/verify_customer_identity.md`](tools/verify_customer_identity.md)** — Full specification for `verify_customer_identity`, including its parameters, session state reads and writes (`idv_status`, `idv_region`, `escalation_reason`, `call_complete`), and two-stage MCP error detection logic.

---

## Glossary

| Term | Definition |
| :--- | :--- |
| **CX Agent Studio (GECX / CXAS)** | Google Cloud's conversational agent platform for building, orchestrating, and deploying voice and chat agents. |
| **MCP Toolset (`mcpToolset`)** | A CXAS toolset resource that connects to an external Model Context Protocol (MCP) server over Streamable HTTP (JSON-RPC 2.0 over HTTP POST). |
| **Pinned Schema Snapshot (`toolOverrides[].snapshot`)** | A static declaration of an MCP tool's `description` and `inputSchema` on the CXAS `Toolset` resource so CXAS can construct model function declarations or validate tool inputs without calling the MCP server's `tools/list` endpoint. |
| **Python Function Tool Controller** | A CXAS `pythonFunction` tool exposed to the language model that invokes underlying MCP or OpenAPI connector tools via the runtime `tools.<toolset>_<op>(...)` interface, catching transport and protocol errors in Python. |
| **Agent-to-Agent (A2A) Protocol** | A protocol (`lf.a2a.v1.A2AService.SendMessage`) used by a calling CXAS application (`personal-banking-a2a-caller`) to delegate a turn to a remote CXAS application (`mortgage-specialist-app`) over HTTPS via `ces.googleapis.com`. |
| **VPC Service Controls (VPC-SC)** | A Google Cloud security boundary that restricts data movement across Google-managed services (`ces.googleapis.com`, `contactcenterinsights.googleapis.com`) using service perimeters, ingress policies, and egress policies. |
| **Allowed Origins (`allowedOrigins`)** | A list of HTTPS origins on the project's CXAS `SecuritySettings` resource (`endpointControlPolicy`) that are permitted to receive outbound non-Service-Directory calls when `enforcementScope` is set to `VPCSC_ONLY` or `ALWAYS`. |
