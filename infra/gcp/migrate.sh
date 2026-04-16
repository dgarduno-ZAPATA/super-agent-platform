#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-chatbots-1-492817}"
REGION="${REGION:-northamerica-south1}"
ACCOUNT_EMAIL="${ACCOUNT_EMAIL:-dgarduno@zapata.com.mx}"
SQL_INSTANCE_NAME="${SQL_INSTANCE_NAME:-}"
DB_PORT="${DB_PORT:-5433}"
SECRET_DATABASE_URL="${SECRET_DATABASE_URL:-DATABASE_URL}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: ${cmd}" >&2
    exit 1
  fi
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

require_command gcloud
require_command curl
require_command python3
require_command psql

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

DATABASE_URL_SECRET="$(
  gcloud secrets versions access latest \
    --secret "${SECRET_DATABASE_URL}" \
    --project "${PROJECT_ID}"
)"

readarray -t URL_VALUES < <(
  DATABASE_URL_SECRET="${DATABASE_URL_SECRET}" python3 - <<'PY'
import os
from urllib.parse import parse_qs, urlparse

raw = os.environ["DATABASE_URL_SECRET"]
parsed = urlparse(raw)
username = parsed.username or ""
password = parsed.password or ""
db_name = parsed.path.lstrip("/")
query = parse_qs(parsed.query)
host = query.get("host", [""])[0]

print(username)
print(password)
print(db_name)
print(host)
PY
)

DB_USER="${URL_VALUES[0]}"
DB_PASSWORD="${URL_VALUES[1]}"
DB_NAME="${URL_VALUES[2]}"
CLOUDSQL_SOCKET_PATH="${URL_VALUES[3]}"

if [[ -z "${DB_USER}" || -z "${DB_PASSWORD}" || -z "${DB_NAME}" ]]; then
  echo "ERROR: Unable to parse DATABASE_URL from Secret Manager." >&2
  exit 1
fi

LOCAL_DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${DB_PORT}/${DB_NAME}"

PROXY_PID=""
trap stop_proxy EXIT

PROXY_BIN="$(ensure_cloud_sql_proxy)"
echo "Starting Cloud SQL Proxy..."
start_proxy "${CONNECTION_NAME}" "${PROXY_BIN}"

echo "Running alembic upgrade head..."
if command -v poetry >/dev/null 2>&1; then
  DATABASE_URL="${LOCAL_DATABASE_URL}" poetry run alembic upgrade head
elif command -v alembic >/dev/null 2>&1; then
  DATABASE_URL="${LOCAL_DATABASE_URL}" alembic upgrade head
else
  echo "ERROR: Neither 'poetry' nor 'alembic' command is available in PATH." >&2
  exit 1
fi

echo "Verifying core tables..."
PGPASSWORD="${DB_PASSWORD}" psql \
  "host=127.0.0.1 port=${DB_PORT} dbname=${DB_NAME} user=${DB_USER} sslmode=disable" \
  -v ON_ERROR_STOP=1 \
  -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('lead_profiles','sessions','conversation_events','silenced_users') ORDER BY table_name;"

echo ""
echo "Migrations completed."
echo "Cloud SQL instance: ${SQL_INSTANCE_NAME}"
echo "Connection: ${CONNECTION_NAME}"
echo "Socket (from secret): ${CLOUDSQL_SOCKET_PATH}"

