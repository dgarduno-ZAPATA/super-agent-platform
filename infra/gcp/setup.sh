#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-chatbots-1-492817}"
REGION="${REGION:-northamerica-south1}"
ACCOUNT_EMAIL="${ACCOUNT_EMAIL:-dgarduno@zapata.com.mx}"

SERVICE_NAME="${SERVICE_NAME:-super-agent-platform}"
SQL_INSTANCE_NAME="${SQL_INSTANCE_NAME:-super-agent-platform-sql}"
DB_NAME="${DB_NAME:-super_agent_platform}"
DB_USER="${DB_USER:-app_user}"
DB_PORT="${DB_PORT:-5433}"

ARTIFACT_REPO="${ARTIFACT_REPO:-super-agent-platform}"
ARTIFACT_REPO_DESC="${ARTIFACT_REPO_DESC:-Docker images for Super Agent Platform}"

SECRET_DATABASE_URL="${SECRET_DATABASE_URL:-DATABASE_URL}"
SECRET_EVOLUTION_BASE_URL="${SECRET_EVOLUTION_BASE_URL:-EVOLUTION_BASE_URL}"
SECRET_EVOLUTION_API_KEY="${SECRET_EVOLUTION_API_KEY:-EVOLUTION_API_KEY}"
SECRET_EVOLUTION_INSTANCE_NAME="${SECRET_EVOLUTION_INSTANCE_NAME:-EVOLUTION_INSTANCE_NAME}"

EVOLUTION_BASE_URL_PLACEHOLDER="${EVOLUTION_BASE_URL_PLACEHOLDER:-https://replace-me.evolution.local}"
EVOLUTION_API_KEY_PLACEHOLDER="${EVOLUTION_API_KEY_PLACEHOLDER:-replace-me}"
EVOLUTION_INSTANCE_NAME_PLACEHOLDER="${EVOLUTION_INSTANCE_NAME_PLACEHOLDER:-replace-me}"

CREATED_RESOURCES=()
REUSED_RESOURCES=()
UPDATED_RESOURCES=()

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: ${cmd}" >&2
    exit 1
  fi
}

append_unique() {
  local value="$1"
  shift
  local -n target_array="$1"
  local existing
  for existing in "${target_array[@]:-}"; do
    if [[ "${existing}" == "${value}" ]]; then
      return 0
    fi
  done
  target_array+=("${value}")
}

generate_password() {
  tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32
}

ensure_cloud_sql_proxy() {
  local proxy_dir="${PWD}/.infra-tools"
  local proxy_bin="${proxy_dir}/cloud-sql-proxy"
  mkdir -p "${proxy_dir}"

  if [[ ! -x "${proxy_bin}" ]]; then
    echo "Downloading cloud-sql-proxy binary..."
    curl -fsSL \
      "https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.linux.amd64" \
      -o "${proxy_bin}"
    chmod +x "${proxy_bin}"
    append_unique "cloud-sql-proxy binary (${proxy_bin})" CREATED_RESOURCES
  else
    append_unique "cloud-sql-proxy binary (${proxy_bin})" REUSED_RESOURCES
  fi

  echo "${proxy_bin}"
}

start_proxy() {
  local connection_name="$1"
  local proxy_bin="$2"
  "${proxy_bin}" "${connection_name}" --port "${DB_PORT}" >/tmp/cloud-sql-proxy.log 2>&1 &
  PROXY_PID=$!
  sleep 3
  if ! kill -0 "${PROXY_PID}" >/dev/null 2>&1; then
    echo "ERROR: Cloud SQL Proxy failed to start. Log:" >&2
    cat /tmp/cloud-sql-proxy.log >&2 || true
    exit 1
  fi
}

stop_proxy() {
  if [[ -n "${PROXY_PID:-}" ]]; then
    kill "${PROXY_PID}" >/dev/null 2>&1 || true
    wait "${PROXY_PID}" 2>/dev/null || true
  fi
}

upsert_secret() {
  local secret_name="$1"
  local secret_value="$2"

  if gcloud secrets describe "${secret_name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${secret_value}" | gcloud secrets versions add "${secret_name}" \
      --project "${PROJECT_ID}" \
      --data-file=-
    append_unique "Secret version: ${secret_name}" UPDATED_RESOURCES
  else
    printf '%s' "${secret_value}" | gcloud secrets create "${secret_name}" \
      --project "${PROJECT_ID}" \
      --replication-policy="automatic" \
      --data-file=-
    append_unique "Secret: ${secret_name}" CREATED_RESOURCES
  fi
}

require_command gcloud
require_command curl
require_command psql

echo "Configuring gcloud project/account..."
gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud config set account "${ACCOUNT_EMAIL}" >/dev/null

echo "Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

echo "Discovering existing Cloud SQL PostgreSQL instances..."
EXISTING_INSTANCE="$(
  gcloud sql instances list \
    --project "${PROJECT_ID}" \
    --filter="DATABASE_VERSION:POSTGRES*" \
    --format="value(name)" | head -n 1
)"

if [[ -n "${EXISTING_INSTANCE}" ]]; then
  SQL_INSTANCE_NAME="${EXISTING_INSTANCE}"
  append_unique "Cloud SQL instance: ${SQL_INSTANCE_NAME}" REUSED_RESOURCES
  echo "Reusing Cloud SQL instance: ${SQL_INSTANCE_NAME}"
else
  echo "No PostgreSQL instance found. Creating ${SQL_INSTANCE_NAME} (db-f1-micro)..."
  gcloud sql instances create "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --database-version "POSTGRES_16" \
    --tier "db-f1-micro" \
    --storage-size "10" \
    --storage-type "SSD"
  append_unique "Cloud SQL instance: ${SQL_INSTANCE_NAME}" CREATED_RESOURCES
fi

CONNECTION_NAME="$(
  gcloud sql instances describe "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}" \
    --format="value(connectionName)"
)"

if gcloud sql databases describe "${DB_NAME}" --instance "${SQL_INSTANCE_NAME}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  append_unique "Cloud SQL database: ${DB_NAME}" REUSED_RESOURCES
  echo "Database already exists: ${DB_NAME}"
else
  echo "Creating database: ${DB_NAME}"
  gcloud sql databases create "${DB_NAME}" \
    --instance "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}"
  append_unique "Cloud SQL database: ${DB_NAME}" CREATED_RESOURCES
fi

DB_PASSWORD="$(generate_password)"

if gcloud sql users list \
  --instance "${SQL_INSTANCE_NAME}" \
  --project "${PROJECT_ID}" \
  --format="value(name)" | grep -Fxq "${DB_USER}"; then
  echo "Updating password for existing SQL user: ${DB_USER}"
  gcloud sql users set-password "${DB_USER}" \
    --instance "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}" \
    --password "${DB_PASSWORD}"
  append_unique "Cloud SQL user password rotated: ${DB_USER}" UPDATED_RESOURCES
else
  echo "Creating SQL user: ${DB_USER}"
  gcloud sql users create "${DB_USER}" \
    --instance "${SQL_INSTANCE_NAME}" \
    --project "${PROJECT_ID}" \
    --password "${DB_PASSWORD}"
  append_unique "Cloud SQL user: ${DB_USER}" CREATED_RESOURCES
fi

DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONNECTION_NAME}"

PROXY_PID=""
trap stop_proxy EXIT

PROXY_BIN="$(ensure_cloud_sql_proxy)"
echo "Starting Cloud SQL Proxy for extension setup..."
start_proxy "${CONNECTION_NAME}" "${PROXY_BIN}"

echo "Enabling pgvector extension (CREATE EXTENSION IF NOT EXISTS vector)..."
if PGPASSWORD="${DB_PASSWORD}" psql \
  "host=127.0.0.1 port=${DB_PORT} dbname=${DB_NAME} user=${DB_USER} sslmode=disable" \
  -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1; then
  append_unique "pgvector extension on ${DB_NAME}" UPDATED_RESOURCES
else
  echo "ERROR: Failed to enable pgvector with user '${DB_USER}'." >&2
  echo "Grant extension privileges (or run with a higher-privileged DB user) and rerun setup." >&2
  exit 1
fi

if gcloud artifacts repositories describe "${ARTIFACT_REPO}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  append_unique "Artifact Registry repo: ${ARTIFACT_REPO}" REUSED_RESOURCES
else
  echo "Creating Artifact Registry repo: ${ARTIFACT_REPO}"
  gcloud artifacts repositories create "${ARTIFACT_REPO}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --repository-format "docker" \
    --description "${ARTIFACT_REPO_DESC}"
  append_unique "Artifact Registry repo: ${ARTIFACT_REPO}" CREATED_RESOURCES
fi

echo "Upserting secrets in Secret Manager..."
upsert_secret "${SECRET_DATABASE_URL}" "${DATABASE_URL}"
upsert_secret "${SECRET_EVOLUTION_BASE_URL}" "${EVOLUTION_BASE_URL_PLACEHOLDER}"
upsert_secret "${SECRET_EVOLUTION_API_KEY}" "${EVOLUTION_API_KEY_PLACEHOLDER}"
upsert_secret "${SECRET_EVOLUTION_INSTANCE_NAME}" "${EVOLUTION_INSTANCE_NAME_PLACEHOLDER}"

echo ""
echo "=== Setup Summary ==="
echo "Project:           ${PROJECT_ID}"
echo "Region:            ${REGION}"
echo "Cloud SQL instance ${SQL_INSTANCE_NAME}"
echo "Connection name:   ${CONNECTION_NAME}"
echo "Database:          ${DB_NAME}"
echo "DB user:           ${DB_USER}"
echo "Artifact repo:     ${ARTIFACT_REPO}"
echo "Service name:      ${SERVICE_NAME}"
echo ""
echo "Created:"
for item in "${CREATED_RESOURCES[@]:-}"; do
  echo "  - ${item}"
done
echo "Reused:"
for item in "${REUSED_RESOURCES[@]:-}"; do
  echo "  - ${item}"
done
echo "Updated:"
for item in "${UPDATED_RESOURCES[@]:-}"; do
  echo "  - ${item}"
done
echo ""
echo "Done. Setup is idempotent and can be rerun safely."

