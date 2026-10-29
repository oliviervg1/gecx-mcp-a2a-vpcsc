#!/usr/bin/env bash
# Removes the test VPC-SC service perimeter, deletes the test CXAS applications
# and resets SecuritySettings allowedOrigins, deletes the Cloud Run FastMCP
# service and test custom Service Account, and optionally deletes the GCP project.
#
# Usage:
#   ./scripts/teardown.sh \
#     --project-id=albion-gcp-project \
#     --region=europe-west2 \
#     --location=eu \
#     [--policy-id=987654321098] \
#     [--perimeter-name=albion_a2a_repro_perimeter] \
#     [--delete-project]

set -euo pipefail

PROJECT_ID=""
REGION="europe-west2"
LOCATION="eu"
SERVICE_NAME="cxas-mcp-repro-server"
CUSTOM_SA_NAME="a2a-custom-caller"
POLICY_ID=""
PERIMETER_NAME="albion_a2a_repro_perimeter"
DELETE_PROJECT="false"

for arg in "$@"; do
  case $arg in
    --project-id=*) PROJECT_ID="${arg#*=}" ;;
    --region=*) REGION="${arg#*=}" ;;
    --location=*) LOCATION="${arg#*=}" ;;
    --service-name=*) SERVICE_NAME="${arg#*=}" ;;
    --custom-sa-name=*) CUSTOM_SA_NAME="${arg#*=}" ;;
    --policy-id=*) POLICY_ID="${arg#*=}" ;;
    --perimeter-name=*) PERIMETER_NAME="${arg#*=}" ;;
    --delete-project) DELETE_PROJECT="true" ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: --project-id is required." >&2
  exit 1
fi

if [[ -n "${POLICY_ID}" ]]; then
  echo "1. Deleting VPC-SC perimeter ${PERIMETER_NAME} from policy ${POLICY_ID}..."
  gcloud access-context-manager perimeters delete "${PERIMETER_NAME}" \
    --policy="${POLICY_ID}" \
    --billing-project="${PROJECT_ID}" \
    --quiet || true
fi

if [[ "${DELETE_PROJECT}" == "true" ]]; then
  echo "2. Deleting project ${PROJECT_ID}..."
  gcloud projects delete "${PROJECT_ID}" --quiet
  echo "Teardown complete."
  exit 0
fi

TOKEN=$(gcloud auth print-access-token)
BASE_URL="https://ces.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${LOCATION}"

echo "2. Deleting test CXAS applications and resetting SecuritySettings in ${PROJECT_ID} (${LOCATION})..."
for app_id in scenario1-mcp-repro personal-banking-a2a-caller mortgage-specialist-app; do
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-goog-user-project: ${PROJECT_ID}" \
    "${BASE_URL}/apps/${app_id}?force=true" >/dev/null || true
done

curl -sS -X PATCH \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  -d '{"endpointControlPolicy":{"enforcementScope":"VPCSC_ONLY","allowedOrigins":[]}}' \
  "${BASE_URL}/securitySettings?updateMask=endpointControlPolicy" >/dev/null || true

echo "3. Deleting Cloud Run service ${SERVICE_NAME} in ${REGION}..."
gcloud run services delete "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --quiet || true

CUSTOM_SA_EMAIL="${CUSTOM_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "4. Removing custom Service Account ${CUSTOM_SA_EMAIL}..."
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${CUSTOM_SA_EMAIL}" \
  --role="roles/ces.client" \
  --quiet >/dev/null 2>&1 || true

gcloud iam service-accounts delete "${CUSTOM_SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --quiet || true

echo "Teardown complete."
