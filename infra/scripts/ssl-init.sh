#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Uso: $0 <DOMAIN> <EMAIL>"
  exit 1
fi

DOMAIN="$1"
EMAIL="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mkdir -p infra/nginx/ssl infra/nginx/www

docker compose -f docker-compose.prod.yml up -d nginx

docker compose -f docker-compose.prod.yml run --rm --profile certbot certbot \
  certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --domain "${DOMAIN}" \
  --email "${EMAIL}" \
  --agree-tos \
  --non-interactive \
  --no-eff-email

docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload

echo "Certificado SSL inicializado para ${DOMAIN}"
