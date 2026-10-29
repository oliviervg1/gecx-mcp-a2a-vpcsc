#!/usr/bin/env python3
"""Phase B verification script: A2A Protocol under an Enforced VPC-SC Perimeter.

Executes five automated verification tests inside an enforced VPC-SC service perimeter
using the cxas-scrapi SDK (Apps, Sessions, and AgentServiceClient):
- Test 2-pre: Enforced perimeter prior to adding https://ces.googleapis.com to CXAS allowedOrigins.
- Test 2A: Default CXAS service agent under enforced VPC-SC without an Egress Rule (reproduces 403 VPC_SERVICE_CONTROLS).
- Test 2B-i: Custom Service Account on RemoteAgentTool while only default CXAS SA is in Egress Rule (reproduces 403 VPC_SERVICE_CONTROLS on Custom SA).
- Test 2B-ii: Custom Service Account in the VPC-SC Egress Rule (resources: ["*"]) and companion Ingress Rule, but missing roles/ces.client (reproduces IAM PERMISSION_DENIED).
- Test 2C: Enforced VPC-SC + allowedOrigins + Egress Rule (resources: ["*"]) + Ingress Rule + roles/ces.client (verifies HTTP 200 OK).
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import uuid

from run_phase_a_mcp_and_a2a_baseline import CxasTestClient


def run_cmd(cmd: list[str]) -> str:
    """Runs a shell command and returns stripped stdout."""
    print(f"+ {' '.join(cmd)}", flush=True)
    return subprocess.check_output(cmd, text=True).strip()


def resolve_project_number(project_id: str, account: str = "") -> str:
    """Resolves the numeric GCP project number from the project ID."""
    cmd = ["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"]
    if account:
        cmd.append(f"--account={account}")
    return run_cmd(cmd)


def resolve_active_account(account: str = "") -> str:
    """Resolves the active gcloud user email if not explicitly provided."""
    if account:
        return account
    return run_cmd(["gcloud", "config", "get-value", "account"])


def collect_spans(
    span: dict[str, Any] | None, out: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Recursively collects diagnostic trace spans from a RunSession response."""
    if out is None:
        out = []
    if not span:
        return out
    out.append(span)
    for child in span.get("childSpans", []):
        collect_spans(child, out)
    return out


def extract_a2a_spans(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Extracts Tool and RemoteAgentTool spans from a RunSession response."""
    all_spans: list[dict[str, Any]] = []
    for out in resp.get("outputs", []):
        root = out.get("diagnosticInfo", {}).get("rootSpan")
        if root:
            collect_spans(root, all_spans)
    matched: list[dict[str, Any]] = []
    for span in all_spans:
        attrs = span.get("attributes", {})
        if attrs and (
            "error" in str(attrs).lower()
            or span.get("name", "") in ("Tool", "mortgage_specialist", "RemoteAgentTool")
        ):
            matched.append({"name": span.get("name"), "attributes": attrs})
    return matched


def run_a2a_turn(client: CxasTestClient, caller_app_id: str, prompt: str) -> tuple[int, dict[str, Any]]:
    """Runs the opening greeting turn followed by the mortgage A2A query turn via cxas-scrapi Sessions."""
    session_id = f"s2-{uuid.uuid4().hex[:8]}"
    client.run_session(caller_app_id, "hi", session_id=session_id)
    status, resp, _ = client.run_session(caller_app_id, prompt, session_id=session_id)
    return status, resp


def update_perimeter(
    policy_id: str,
    perimeter_name: str,
    project_id: str,
    project_number: str,
    ingress_yaml_content: str,
    egress_yaml_content: str | None = None,
    account: str = "",
) -> None:
    """Creates or updates the VPC-SC regular perimeter with the provided ingress/egress rules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ingress_path = Path(tmpdir) / "ingress.yaml"
        ingress_path.write_text(ingress_yaml_content, encoding="utf-8")

        list_cmd = [
            "gcloud",
            "access-context-manager",
            "perimeters",
            "list",
            f"--policy={policy_id}",
            f"--billing-project={project_id}",
            "--format=value(name.basename())",
        ]
        if account:
            list_cmd.append(f"--account={account}")
        existing = [x.strip() for x in run_cmd(list_cmd).splitlines()]

        if perimeter_name not in existing:
            create_cmd = [
                "gcloud",
                "access-context-manager",
                "perimeters",
                "create",
                perimeter_name,
                f"--policy={policy_id}",
                f"--title={perimeter_name}",
                "--perimeter-type=regular",
                f"--resources=projects/{project_number}",
                "--restricted-services=ces.googleapis.com,contactcenterinsights.googleapis.com",
                f"--ingress-policies={ingress_path}",
                f"--billing-project={project_id}",
                "--quiet",
            ]
            if account:
                create_cmd.append(f"--account={account}")
            run_cmd(create_cmd)

        update_cmd = [
            "gcloud",
            "access-context-manager",
            "perimeters",
            "update",
            perimeter_name,
            f"--policy={policy_id}",
            f"--set-ingress-policies={ingress_path}",
            f"--billing-project={project_id}",
            "--quiet",
        ]
        if egress_yaml_content:
            egress_path = Path(tmpdir) / "egress.yaml"
            egress_path.write_text(egress_yaml_content, encoding="utf-8")
            update_cmd.append(f"--set-egress-policies={egress_path}")
        else:
            update_cmd.append("--clear-egress-policies")
        if account:
            update_cmd.append(f"--account={account}")
        run_cmd(update_cmd)


def run_phase_b(
    client: CxasTestClient,
    project_number: str,
    policy_id: str,
    perimeter_name: str,
    admin_email: str,
    custom_sa: str,
    mcp_url: str,
    output_file: str,
) -> dict[str, Any]:
    """Executes Phase B VPC-SC A2A verification tests (2-pre, 2A, 2B-i, 2B-ii, 2C) via cxas-scrapi."""
    results: dict[str, Any] = {}
    caller_app_id = "personal-banking-a2a-caller"
    mortgage_app_id = "mortgage-specialist-app"
    ces_sa = f"service-{project_number}@gcp-sa-ces.iam.gserviceaccount.com"
    prompt = "What is the 5-year fixed mortgage rate and the annual overpayment allowance?"

    admin_only_ingress = f"""- ingressFrom:
    identities:
      - user:{admin_email}
    sources:
      - accessLevel: "*"
  ingressTo:
    operations:
      - serviceName: "*"
    resources:
      - "*"
"""

    admin_and_sa_ingress = f"""- ingressFrom:
    identities:
      - user:{admin_email}
    sources:
      - accessLevel: "*"
  ingressTo:
    operations:
      - serviceName: "*"
    resources:
      - "*"
- ingressFrom:
    identities:
      - serviceAccount:{ces_sa}
      - serviceAccount:{custom_sa}
    sources:
      - accessLevel: "*"
  ingressTo:
    resources:
      - projects/{project_number}
    operations:
      - serviceName: ces.googleapis.com
        methodSelectors:
          - method: "*"
"""

    egress_ces_only = f"""- egressFrom:
    identities:
      - serviceAccount:{ces_sa}
  egressTo:
    operations:
      - serviceName: ces.googleapis.com
        methodSelectors:
          - method: "*"
    resources:
      - "*"
"""

    egress_both_sas = f"""- egressFrom:
    identities:
      - serviceAccount:{ces_sa}
      - serviceAccount:{custom_sa}
  egressTo:
    operations:
      - serviceName: ces.googleapis.com
        methodSelectors:
          - method: "*"
    resources:
      - "*"
"""

    # Ensure custom_sa does not have roles/ces.client from a previous run so 2B-ii is reproducible
    remove_iam_cmd = [
        "gcloud",
        "projects",
        "remove-iam-policy-binding",
        client.project_id,
        f"--member=serviceAccount:{custom_sa}",
        "--role=roles/ces.client",
        "--quiet",
    ]
    if client.account:
        remove_iam_cmd.append(f"--account={client.account}")
    subprocess.run(remove_iam_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    # Reset SecuritySettings allowedOrigins to empty via AgentServiceClient so Test 2-pre is reproducible
    client.update_security_settings(allowed_origins=[])

    # Push A2A target and caller bundles with default CXAS service agent (custom_sa=None) via cxas-scrapi
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

    # 1. Test 2-pre: Enforced perimeter prior to allowedOrigins configuration
    print("\n=== Test 2-pre: Enforced VPC-SC Perimeter Prior to allowedOrigins Configuration ===")
    update_perimeter(
        policy_id,
        perimeter_name,
        client.project_id,
        project_number,
        admin_only_ingress,
        egress_yaml_content=None,
        account=client.account,
    )
    time.sleep(20)
    st_pre, resp_pre = run_a2a_turn(client, caller_app_id, prompt)
    spans_pre = extract_a2a_spans(resp_pre)
    print(f"Test 2-pre -> HTTP {st_pre}, spans={json.dumps(spans_pre, indent=2)}")
    results["test_2_pre"] = {"status": st_pre, "spans": spans_pre, "response": resp_pre}

    # 2. Configure CXAS SecuritySettings allowedOrigins and wait for cache expiry
    print("\n=== Updating CXAS SecuritySettings.endpointControlPolicy.allowedOrigins ===")
    client.update_security_settings(
        allowed_origins=[
            "https://ces.googleapis.com",
            mcp_url.rstrip("/"),
        ]
    )
    print("Waiting 190s (idle) for CXAS SecuritySettings propagation...")
    time.sleep(190)

    # 3. Test 2A: Default CXAS Service Agent without VPC-SC Egress Rule -> 403 VPC_SERVICE_CONTROLS
    print("\n=== Test 2A: Default CXAS Service Agent Without VPC-SC Egress Rule ===")
    st_2a, resp_2a = run_a2a_turn(client, caller_app_id, prompt)
    spans_2a = extract_a2a_spans(resp_2a)
    print(f"Test 2A -> HTTP {st_2a}, spans={json.dumps(spans_2a, indent=2)}")
    results["test_2A"] = {"status": st_2a, "spans": spans_2a, "response": resp_2a}

    # 4. Test 2B-i: Push Caller bundle with Custom SA on RemoteAgentTool via cxas-scrapi Apps.import_app
    print("\n=== Test 2B-i: Custom SA on RemoteAgentTool Without Egress Rule for Custom SA ===")
    client.push_app_bundle(
        app_id=caller_app_id,
        bundle_name="Albion_Bank_Personal_Banking_A2A_Caller",
        replacements={"apps/mortgage-specialist-app": f"apps/{mortgage_app_id}"},
        custom_sa=custom_sa,
    )
    update_perimeter(
        policy_id,
        perimeter_name,
        client.project_id,
        project_number,
        admin_and_sa_ingress,
        egress_yaml_content=egress_ces_only,
        account=client.account,
    )
    print("Waiting 70s for tool configuration and perimeter propagation...")
    time.sleep(70)
    st_2bi, resp_2bi = run_a2a_turn(client, caller_app_id, prompt)
    spans_2bi = extract_a2a_spans(resp_2bi)
    print(f"Test 2B-i -> HTTP {st_2bi}, spans={json.dumps(spans_2bi, indent=2)}")
    results["test_2Bi"] = {"status": st_2bi, "spans": spans_2bi, "response": resp_2bi}

    # 5. Test 2B-ii: Add Custom SA to Egress Rule (resources: ["*"]) without roles/ces.client -> IAM PERMISSION_DENIED
    print("\n=== Test 2B-ii: Custom SA in VPC-SC Egress Rule, Missing roles/ces.client ===")
    update_perimeter(
        policy_id,
        perimeter_name,
        client.project_id,
        project_number,
        admin_and_sa_ingress,
        egress_yaml_content=egress_both_sas,
        account=client.account,
    )
    time.sleep(25)
    st_2bii, resp_2bii = run_a2a_turn(client, caller_app_id, prompt)
    spans_2bii = extract_a2a_spans(resp_2bii)
    print(f"Test 2B-ii -> HTTP {st_2bii}, spans={json.dumps(spans_2bii, indent=2)}")
    results["test_2Bii"] = {"status": st_2bii, "spans": spans_2bii, "response": resp_2bii}

    # 6. Test 2C: Grant roles/ces.client to Custom SA -> 200 OK under Enforced VPC-SC
    print("\n=== Test 2C: Grant roles/ces.client + VPC-SC Egress Rule (resources: ['*']) -> 200 OK ===")
    iam_cmd = [
        "gcloud",
        "projects",
        "add-iam-policy-binding",
        client.project_id,
        f"--member=serviceAccount:{custom_sa}",
        "--role=roles/ces.client",
        "--quiet",
    ]
    if client.account:
        iam_cmd.append(f"--account={client.account}")
    run_cmd(iam_cmd)
    print("Waiting 60s for IAM binding propagation...")
    time.sleep(60)
    st_2c, resp_2c = run_a2a_turn(client, caller_app_id, prompt)
    spans_2c = extract_a2a_spans(resp_2c)
    print(f"Test 2C -> HTTP {st_2c}")
    print(json.dumps(resp_2c, indent=2))
    results["test_2C"] = {"status": st_2c, "spans": spans_2c, "response": resp_2c}

    Path(output_file).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved Phase B results to {output_file}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase B VPC-SC A2A verification tests via cxas-scrapi."
    )
    parser.add_argument("--project-id", required=True, help="Target GCP project ID")
    parser.add_argument(
        "--project-number",
        default="",
        help="Target GCP project number (auto-resolved from --project-id if omitted)",
    )
    parser.add_argument("--policy-id", required=True, help="Access Context Manager policy ID")
    parser.add_argument(
        "--perimeter-name",
        default="albion_a2a_repro_perimeter",
        help="VPC-SC service perimeter name (default: albion_a2a_repro_perimeter)",
    )
    parser.add_argument(
        "--admin-email",
        default="",
        help="Admin user email for perimeter ingress (auto-resolved from gcloud config if omitted)",
    )
    parser.add_argument(
        "--custom-sa",
        default="",
        help="Custom service account email (defaults to a2a-custom-caller@<project-id>.iam.gserviceaccount.com)",
    )
    parser.add_argument("--mcp-url", required=True, help="Deployed Cloud Run FastMCP base URL")
    parser.add_argument("--location", default="eu", help="CXAS region (default: eu)")
    parser.add_argument("--account", default="", help="Optional gcloud account email")
    parser.add_argument(
        "--output", default="phase_b_results.json", help="Output JSON path for test results"
    )
    args = parser.parse_args()

    project_number = args.project_number or resolve_project_number(args.project_id, args.account)
    admin_email = args.admin_email or resolve_active_account(args.account)
    custom_sa = args.custom_sa or f"a2a-custom-caller@{args.project_id}.iam.gserviceaccount.com"

    client = CxasTestClient(args.project_id, args.location, args.account)
    run_phase_b(
        client=client,
        project_number=project_number,
        policy_id=args.policy_id,
        perimeter_name=args.perimeter_name,
        admin_email=admin_email,
        custom_sa=custom_sa,
        mcp_url=args.mcp_url,
        output_file=args.output,
    )


if __name__ == "__main__":
    main()
