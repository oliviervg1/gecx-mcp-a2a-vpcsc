#!/usr/bin/env bash
# Enables required GCP APIs, provisions the CXAS Service Agent and custom A2A
# Service Account (including serviceAccountTokenCreator binding), deploys the
# dual-route FastMCP test server to Cloud Run, and configures path-qualified
# OIDC custom audiences.
#
# Usage:
#   ./scripts/deploy_mcp_server.sh \
#     --project-id=albion-gcp-project \
#     --region=europe-west2 \
#     --service-name=cxas-mcp-repro-server \
#     --custom-sa-name=a2a-custom-caller \
#     [--account=admin@example.com]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID=""
REGION="europe-west2"
SERVICE_NAME="cxas-mcp-repro-server"
CUSTOM_SA_NAME="a2a-custom-caller"
ACCOUNT="${CLOUDSDK_CORE_ACCOUNT:-}"

for arg in "$@"; do
  case $arg in
    --project-id=*) PROJECT_ID="${arg#*=}" ;;
    --region=*) REGION="${arg#*=}" ;;
    --service-name=*) SERVICE_NAME="${arg#*=}" ;;
    --custom-sa-name=*) CUSTOM_SA_NAME="${arg#*=}" ;;
    --account=*) ACCOUNT="${arg#*=}" ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [[ -n "${ACCOUNT}" ]]; then
  export CLOUDSDK_CORE_ACCOUNT="${ACCOUNT}"
fi

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: --project-id is required." >&2
  exit 1
fi

echo "1. Enabling required Google Cloud APIs in ${PROJECT_ID}..."
gcloud services enable \
  ces.googleapis.com \
  contactcenterinsights.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  accesscontextmanager.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet

echo "2. Ensuring CXAS Service Agent identity exists..."
gcloud beta services identity create \
  --service=ces.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
CXAS_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com"
CUSTOM_SA_EMAIL="${CUSTOM_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "3. Ensuring custom A2A Service Account (${CUSTOM_SA_EMAIL}) exists and granting Token Creator to CXAS Service Agent..."
if ! gcloud iam service-accounts describe "${CUSTOM_SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${CUSTOM_SA_NAME}" \
    --display-name="Albion Bank Custom A2A Caller SA" \
    --project="${PROJECT_ID}" \
    --quiet
  sleep 5
fi

for attempt in 1 2 3 4 5; do
  if gcloud iam service-accounts add-iam-policy-binding "${CUSTOM_SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${CXAS_SERVICE_AGENT}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --quiet >/dev/null 2>&1; then
    break
  fi
  echo "  Waiting for service account IAM propagation (attempt ${attempt}/5)..."
  sleep 5
done

echo "3b. Ensuring Compute Engine default service account has roles/cloudbuild.builds.builder for Cloud Run source builds..."
gcloud beta services identity create \
  --service=compute.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet >/dev/null 2>&1 || true
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for attempt in 1 2 3 4 5; do
  if gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/cloudbuild.builds.builder" \
    --quiet >/dev/null 2>&1; then
    break
  fi
  echo "  Waiting for Compute SA IAM propagation (attempt ${attempt}/5)..."
  sleep 5
done

echo "4. Deploying ${SERVICE_NAME} to Cloud Run in ${PROJECT_ID} (${REGION})..."
for attempt in 1 2 3; do
  if gcloud run deploy "${SERVICE_NAME}" \
    --source="${REPO_ROOT}/mcp_server" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --no-allow-unauthenticated \
    --quiet; then
    break
  fi
  if [[ "${attempt}" -eq 3 ]]; then
    echo "Error: Cloud Run deployment failed after 3 attempts." >&2
    exit 1
  fi
  echo "  Retrying Cloud Run source deployment after initial IAM/Artifact Registry propagation (attempt ${attempt}/3)..."
  sleep 10
done

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(status.url)")

echo "5. Configuring custom OIDC audiences for path-qualified MCP URLs..."
gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --add-custom-audiences="${SERVICE_URL}/mcp1,${SERVICE_URL}/mcp1/,${SERVICE_URL}/mcp2,${SERVICE_URL}/mcp2/" \
  --quiet

echo "6. Granting roles/run.invoker to the CXAS Service Agent (${CXAS_SERVICE_AGENT})..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${CXAS_SERVICE_AGENT}" \
  --role="roles/run.invoker" \
  --quiet >/dev/null

echo ""
echo "Deployment complete!"
echo "Cloud Run URL: ${SERVICE_URL}"
echo "  Unhealthy primary route (returns HTTP 400): ${SERVICE_URL}/mcp1/"
echo "  Healthy secondary route (FastMCP):          ${SERVICE_URL}/mcp2/"
echo "  Custom A2A Caller SA:                       ${CUSTOM_SA_EMAIL}"
echo ""
echo "Export these variables for Phase A and Phase B:"
echo "  export MCP_URL=\"${SERVICE_URL}\""
echo "  export CUSTOM_SA=\"${CUSTOM_SA_EMAIL}\""
