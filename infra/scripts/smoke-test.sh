#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
USERNAME="${ADMIN_USERNAME:-admin}"
PASSWORD="${ADMIN_PASSWORD:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() {
  printf "${GREEN}PASS${NC} %s\n" "$1"
}

fail() {
  printf "${RED}FAIL${NC} %s\n" "$1"
}

if [[ -z "${PASSWORD}" ]]; then
  printf "${YELLOW}WARN${NC} ADMIN_PASSWORD no definido; exportalo antes de correr el smoke test.\n"
  exit 1
fi

overall_ok=0

# 1) GET /health
health_code="$(curl -sS -o /tmp/smoke_health.json -w "%{http_code}" "${BASE_URL}/health" || true)"
if [[ "${health_code}" == "200" ]]; then
  pass "GET /health -> 200"
else
  fail "GET /health esperado 200, recibido ${health_code}"
  overall_ok=1
fi

# 2) POST /auth/token
token_resp="$(curl -sS -X POST "${BASE_URL}/api/v1/auth/token" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" || true)"

token="$(printf "%s" "${token_resp}" | python -c "import json,sys; print(json.loads(sys.stdin.read()).get('access_token',''))" 2>/dev/null || true)"
if [[ -n "${token}" ]]; then
  pass "POST /api/v1/auth/token -> token emitido"
else
  fail "POST /api/v1/auth/token no retorno access_token"
  overall_ok=1
fi

# 3) GET /dashboard/stats con token
dashboard_code="$(curl -sS -o /tmp/smoke_dashboard.json -w "%{http_code}" \
  "${BASE_URL}/api/v1/dashboard/stats" \
  -H "Authorization: Bearer ${token}" || true)"
if [[ "${dashboard_code}" == "200" ]]; then
  pass "GET /api/v1/dashboard/stats -> 200"
else
  fail "GET /api/v1/dashboard/stats esperado 200, recibido ${dashboard_code}"
  overall_ok=1
fi

# 4) POST /webhooks/whatsapp con payload de prueba
webhook_payload='{
  "event": "messages.upsert",
  "instance": "smoke",
  "data": {
    "key": {"id": "smoke-test-1", "fromMe": false, "remoteJid": "5215550000000@s.whatsapp.net"},
    "message": {"conversation": "Hola desde smoke test"},
    "messageTimestamp": 1710000000
  }
}'
webhook_code="$(curl -sS -o /tmp/smoke_webhook.json -w "%{http_code}" \
  -X POST "${BASE_URL}/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -d "${webhook_payload}" || true)"
if [[ "${webhook_code}" == "200" ]]; then
  pass "POST /webhooks/whatsapp -> 200"
else
  fail "POST /webhooks/whatsapp esperado 200, recibido ${webhook_code}"
  overall_ok=1
fi

if [[ "${overall_ok}" -eq 0 ]]; then
  printf "${GREEN}SMOKE TEST RESULT: PASS${NC}\n"
  exit 0
fi

printf "${RED}SMOKE TEST RESULT: FAIL${NC}\n"
exit 1
