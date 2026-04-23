#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-chatbots-1-492817}"
REGION="${REGION:-northamerica-south1}"
ACCOUNT_EMAIL="${ACCOUNT_EMAIL:-dgarduno@zapata.com.mx}"

SERVICE_NAME="${SERVICE_NAME:-super-agent-platform}"
ARTIFACT_REPO="${ARTIFACT_REPO:-super-agent-platform}"
SQL_INSTANCE_NAME="${SQL_INSTANCE_NAME:-}"

TAG="${TAG:-$(date +%Y%m%d-%H%M%S)}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}:${TAG}"

SECRET_DATABASE_URL="${SECRET_DATABASE_URL:-DATABASE_URL}"
SECRET_EVOLUTION_BASE_URL="${SECRET_EVOLUTION_BASE_URL:-EVOLUTION_BASE_URL}"
SECRET_EVOLUTION_API_KEY="${SECRET_EVOLUTION_API_KEY:-EVOLUTION_API_KEY}"
SECRET_EVOLUTION_INSTANCE_NAME="${SECRET_EVOLUTION_INSTANCE_NAME:-EVOLUTION_INSTANCE_NAME}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: ${cmd}" >&2
    exit 1
  fi
}

require_command gcloud
require_command docker

echo "Configuring gcloud project/account..."
gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud config set account "${ACCOUNT_EMAIL}" >/dev/null

if [[ -z "${SQL_INSTANCE_NAME}" ]]; then
  SQL_INSTANCE_NAME="$(
    gcloud sql instances list \
      --project "${PROJECT_ID}" \
      --filter="DATABASE_VERSION:POSTGRES*" \
      --format="value(name)" | head -n 1
  )"
fi

if [[ -z "${SQL_INSTANCE_NAME}" ]]; then
  echo "ERROR: No PostgreSQL Cloud SQL instance found. Run infra/gcp/setup.sh first." >&2
  exit 1
fi

CONNECTION_NAME="$(
  gcloud sql instances describe "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}" \
    --format="value(connectionName)"
)"

echo "Configuring docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet >/dev/null

echo "Building image ${IMAGE_URI} from Dockerfile target 'prod'..."
docker build --target prod -t "${IMAGE_URI}" .

echo "Pushing image ${IMAGE_URI}..."
docker push "${IMAGE_URI}"

echo "Deploying Cloud Run service ${SERVICE_NAME}..."
gcloud run deploy "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform "managed" \
  --image "${IMAGE_URI}" \
  --port "8000" \
  --add-cloudsql-instances "${CONNECTION_NAME}" \
  --set-secrets "DATABASE_URL=${SECRET_DATABASE_URL}:latest,EVOLUTION_BASE_URL=${SECRET_EVOLUTION_BASE_URL}:latest,EVOLUTION_API_KEY=${SECRET_EVOLUTION_API_KEY}:latest,EVOLUTION_INSTANCE_NAME=${SECRET_EVOLUTION_INSTANCE_NAME}:latest,MONDAY_API_KEY=MONDAY_API_KEY:latest,MONDAY_BOARD_ID=MONDAY_BOARD_ID:latest" \
  --min-instances "0" \
  --max-instances "2" \
  --memory "512Mi" \
  --cpu "1" \
  --timeout "300" \
  --allow-unauthenticated

SERVICE_URL="$(
  gcloud run services describe "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --format="value(status.url)"
)"

echo ""
echo "Cloud Run URL: ${SERVICE_URL}"
echo "Deployed image: ${IMAGE_URI}"
echo "Cloud SQL connection: ${CONNECTION_NAME}"
