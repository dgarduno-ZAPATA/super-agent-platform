#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

if [[ ! -f .env ]]; then
  echo ".env no encontrado en ${REPO_ROOT}"
  exit 1
fi

set -a
source .env
set +a

mkdir -p backups
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_FILE="backups/${POSTGRES_DB}_${TIMESTAMP}.sql"

docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" > "${OUTPUT_FILE}"

echo "Backup creado: ${OUTPUT_FILE}"
