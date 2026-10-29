# Albion Bank — CX Agent Studio (GECX) MCP Regional Failover & A2A VPC-SC Verification Suite

> **Disclaimer:** This repository is an unofficial reference implementation and is not an officially supported Google product. "Albion Bank" (`albion-gcp-project`) is a fictional institution used strictly for illustration.

This repository provides a complete, customer-reproducible reference implementation and live verification suite for two enterprise integration patterns in CX Agent Studio (GECX):

1. **Model Context Protocol (MCP) Session Initialization, Error Interception, and Regional Failover:** Reproduces the unhandled HTTP 400 `FAILED_PRECONDITION` crash that occurs when an MCP toolset is attached directly to a sub-agent and its primary endpoint fails during session initialization. Demonstrates how invoking the MCP toolsets from a Python Function Tool controller (`verify_customer_identity`) — with the MCP toolsets omitted from the sub-agent's `toolsets` list and configured with `toolOverrides` schema snapshots where supported — eliminates entry-time network calls and automatically fails over from an unhealthy primary route (`/mcp1`, simulating `europe-west2`) to a healthy secondary route (`/mcp2`, simulating `europe-west1`).
2. **Agent-to-Agent (A2A) Protocol Connectivity Under VPC Service Controls (VPC-SC):** Reproduces and resolves the `PERMISSION_DENIED` (`VPC_SERVICE_CONTROLS` / `RESOURCES_NOT_IN_SAME_SERVICE_PERIMETER`) error when a calling CXAS application invokes a remote CXAS application over the native A2A protocol inside an enforced VPC-SC service perimeter, covering outbound `allowedOrigins`, perimeter `egressPolicies` (`resources: ["*"]`) and `ingressPolicies`, and custom Service Account IAM alignment.

```
Customer Utterance ("Verify my identity for customer ID CUST-101")
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ CX Agent Studio (GECX) Sub-Agent (idv_sub_agent)                     │
│  • Attached Tool: verify_customer_identity (Python Function Tool)    │
│  • MCP Toolsets omitted from sub-agent toolsets[] to prevent         │
│    unhandled entry-time initialize / tools/list crashes              │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
       ┌───────────────────────┴───────────────────────┐
       ▼ (1. Primary Attempt)                          ▼ (2. Automatic Failover)
┌─────────────────────────────────────┐         ┌─────────────────────────────────────┐
│ customer_idv_primary (/mcp1)        │         │ customer_idv_secondary (/mcp2)      │
│  • Simulates regional proxy outage  │  HTTP   │  • Returns verified customer record │
│    (HTTP 400 Bad Request)           │ ──400─► │    (region: europe-west1-secondary) │
└─────────────────────────────────────┘         └─────────────────────────────────────┘
```

> **Note:** For convenience and single-command deployment, both `/mcp1` (simulating an unhealthy `europe-west2` primary proxy returning HTTP 400) and `/mcp2` (simulating a healthy `europe-west1` secondary FastMCP server) are hosted on a single dual-route Cloud Run service (`mcp_server/main.py`).

---

## Quickstart (2 Minutes — Offline Unit Tests, No GCP Project Required)

You can run the full offline unit test suite locally to verify the Python Function Tool failover controller and the dual-route FastMCP test server without deploying any cloud resources:

```bash
uv sync --extra dev
uv run pytest -v
```

The offline test suite (`9 passed`) verifies:
- Primary MCP endpoint success when `/mcp1` is healthy (`idv_status = "VERIFIED"`, `idv_region = "europe-west2-primary"`).
- Automatic regional failover to `/mcp2` when `/mcp1` returns either an HTTP 400 transport error (`resp.ok == False`) or a call-time MCP protocol error envelope (`body.get("status") == "error"`), setting `idv_status = "VERIFIED"` and `idv_region = "europe-west1-secondary"`.
- Graceful degradation when both primary and secondary MCP endpoints are unreachable (`idv_status = "UNAVAILABLE"`).
- Missing customer ID prompting before any MCP network call is attempted.
- Dual-route FastMCP ASGI application routing (`/healthz` returning `200`, `/mcp1` returning `400 Bad Request`, and `/mcp2` serving both `initialize` and `tools/call` for `verify_customer`).

---

## Core Building Blocks

| Component | Path | Purpose |
| :--- | :--- | :--- |
| **Dual-Route FastMCP Server** | [`mcp_server/main.py`](mcp_server/main.py) | Containerized Python server exposing `/mcp1` (simulates a broken regional proxy returning HTTP 400) and `/mcp2` (healthy FastMCP Streamable HTTP endpoint serving `verify_customer`). |
| **Python Failover Controller** | [`tools/verify_customer_identity/python_function/python_code.py`](tools/verify_customer_identity/python_function/python_code.py) | Production CXAS Python Function Tool that intercepts both HTTP transport failures and call-time MCP errors, failing over from `customer_idv_primary` to `customer_idv_secondary`. |
| **VPC-SC Policy Templates** | [`vpcsc_policies/`](vpcsc_policies/) | Ready-to-apply `gcloud access-context-manager perimeters update` YAML specifications for `egressPolicies` (`resources: ["*"]`) and `ingressPolicies` on `ces.googleapis.com`. |
| **End-to-End Cloud Scripts** | [`scripts/`](scripts/) | Automated Python and Bash scripts that enable APIs, deploy the MCP server to Cloud Run, and execute all 10 verification test cases (`1A`, `1B-i`, `1B-ii`, `1B-iii`, `2-0`, `2-pre`, `2A`, `2B-i`, `2B-ii`, and `2C`) against the CXAS v1beta API. |

---

## Running the Live End-to-End Verification in Your GCP Environment

> [!CAUTION]
> **Run Phase B only in a dedicated, disposable test project.** `scripts/run_phase_b_vpcsc_a2a.py` creates an **enforced** VPC Service Controls regular perimeter (`ces.googleapis.com` and `contactcenterinsights.googleapis.com`) around the target project and updates project-level CXAS `SecuritySettings.endpointControlPolicy.allowedOrigins`. Do not run Phase B against a shared or production project, or a project that already belongs to another regular VPC-SC service perimeter.

### Prerequisites

1. Python `>=3.11` and [`uv`](https://docs.astral.sh/uv/) installed locally.
2. Google Cloud SDK (`gcloud`) with the `beta` component installed (`gcloud components install beta`) and an authenticated session (`gcloud auth login`).
3. A dedicated Google Cloud test project (for example, `albion-gcp-project`) with billing enabled where you have permissions to enable APIs, deploy Cloud Run services, manage IAM bindings, and create CX Agent Studio applications.
4. If running Phase B (VPC Service Controls A2A verification), an Organization Access Policy ID (`POLICY_ID`) and the Access Context Manager Admin role (`roles/accesscontextmanager.policyAdmin`) at the organization level.

### Step 1: Deploy the Dual-Route FastMCP Server & Provision Identities

Run `deploy_mcp_server.sh` to enable the required APIs (`ces.googleapis.com`, `contactcenterinsights.googleapis.com`, `run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`, `accesscontextmanager.googleapis.com`), create the CXAS Service Agent and custom A2A caller Service Account (`a2a-custom-caller`), grant `roles/iam.serviceAccountTokenCreator` to the CXAS Service Agent, and deploy the dual-route FastMCP server to Cloud Run:

```bash
export PROJECT_ID="albion-gcp-project"
export REGION="europe-west2"

./scripts/deploy_mcp_server.sh \
  --project-id="${PROJECT_ID}" \
  --region="${REGION}"
```

When deployment finishes, export the `MCP_URL` printed at the end of the script output:

```bash
export MCP_URL="https://cxas-mcp-repro-server-xxxxxxxxxx-nw.a.run.app"
```

### Step 2: Run Phase A (MCP Failover & Baseline A2A Verification — Prior to VPC-SC)

Phase A provisions the CXAS test applications (`scenario1-mcp-repro`, `personal-banking-a2a-caller`, and `mortgage-specialist-app`) in `eu`, executes the 5 pre-perimeter verification tests (`1A`, `1B-i`, `1B-ii`, `1B-iii`, and `2-0`), and writes the full JSON responses to `phase_a_results.json`:

```bash
uv run python scripts/run_phase_a_mcp_and_a2a_baseline.py \
  --project-id="${PROJECT_ID}" \
  --location="eu" \
  --mcp-url="${MCP_URL}"
```

### Step 3: Run Phase B (VPC Service Controls A2A Matrix)

Phase B places your test project inside an enforced VPC-SC service perimeter (`albion_a2a_repro_perimeter`) and runs the 5 progressive VPC-SC and IAM verification tests (`2-pre`, `2A`, `2B-i`, `2B-ii`, and `2C`), saving the diagnostic trace spans and responses to `phase_b_results.json`:

```bash
export POLICY_ID="987654321098"
export PERIMETER_NAME="albion_a2a_repro_perimeter"

uv run python scripts/run_phase_b_vpcsc_a2a.py \
  --project-id="${PROJECT_ID}" \
  --location="eu" \
  --policy-id="${POLICY_ID}" \
  --perimeter-name="${PERIMETER_NAME}" \
  --mcp-url="${MCP_URL}"
```

*(Note: `--project-number`, `--admin-email`, and `--custom-sa` are automatically resolved from your `gcloud` environment if omitted.)*

### Step 4: Teardown Cloud Resources

To delete the VPC-SC test perimeter, delete the test CXAS applications, reset `SecuritySettings.endpointControlPolicy.allowedOrigins`, remove the Cloud Run service, and delete the custom Service Account (or pass `--delete-project` to delete the entire test project):

```bash
./scripts/teardown.sh \
  --project-id="${PROJECT_ID}" \
  --region="${REGION}" \
  --location="eu" \
  --policy-id="${POLICY_ID}" \
  --perimeter-name="${PERIMETER_NAME}"
```

---

## Repository Structure & Documentation Map

```
gecx-mcp-a2a-vpcsc/
├── LICENSE                                                # Apache-2.0 License
├── README.md                                              # Root onboarding & replication guide
├── CHANGELOG.md                                           # Chronological release notes
├── pyproject.toml                                         # Python dependencies & pytest config
├── mcp_server/
│   ├── Dockerfile                                         # Non-root Cloud Run container definition
│   ├── requirements.txt                                   # Pinned FastMCP & Starlette dependencies
│   └── main.py                                            # Dual-route (/mcp1 400, /mcp2 200) server
├── tools/
│   └── verify_customer_identity/
│       └── python_function/
│           └── python_code.py                             # CXAS Python Function Tool failover wrapper
├── vpcsc_policies/
│   ├── egress_a2a_cxas.yaml                               # VPC-SC Egress Rule (resources: ["*"])
│   └── ingress_a2a_cxas.yaml                              # VPC-SC Ingress Rule for ces.googleapis.com
├── scripts/
│   ├── deploy_mcp_server.sh                               # Enables APIs, creates SAs, deploys Cloud Run
│   ├── run_phase_a_mcp_and_a2a_baseline.py                # Runs Tests 1A, 1B-i, 1B-ii, 1B-iii, and 2-0
│   ├── run_phase_b_vpcsc_a2a.py                           # Runs Tests 2-pre, 2A, 2B-i, 2B-ii, and 2C
│   └── teardown.sh                                        # Cleans up perimeter, CXAS apps, Cloud Run, SAs
├── tests/
│   ├── test_mcp_server.py                                 # Offline ASGI tests for /mcp1 and /mcp2
│   └── test_verify_customer_identity.py                   # Offline unit tests for failover controller
└── docs/
    ├── README.md                                          # Documentation hub & navigation index
    ├── guides/
    │   └── mcp_and_a2a_technical_guide.md                 # Architectural deep dive & configuration guide
    ├── architecture/
    │   └── end_to_end_verification_walkthrough.md         # Live test matrix & Cloud Audit Log traces
    └── tools/
        ├── README.md                                      # Tool catalog & line-level reference index
        └── verify_customer_identity.md                    # Specification for verify_customer_identity
```

- **[Documentation Hub (`docs/README.md`)](docs/README.md)** — Start here for role-based navigation and a glossary of CXAS, MCP, A2A, and VPC-SC concepts.
- **[MCP Error Handling, Regional Failover & A2A Technical Guide (`docs/guides/mcp_and_a2a_technical_guide.md`)](docs/guides/mcp_and_a2a_technical_guide.md)** — Detailed architectural explanation of MCP session initialization timing, `toolOverrides` schema snapshots, and VPC-SC evaluation of `A2AService.SendMessage`.
- **[End-to-End Verification Walkthrough (`docs/architecture/end_to_end_verification_walkthrough.md`)](docs/architecture/end_to_end_verification_walkthrough.md)** — Complete walkthrough of all 10 test cases (`1A` through `2C`) with exact request/response payloads and Cloud Audit Log entries.
- **[Python Tool Documentation (`docs/tools/README.md`)](docs/tools/README.md)** — Line-numbered specification and control-flow diagram for [`verify_customer_identity`](docs/tools/verify_customer_identity.md).
