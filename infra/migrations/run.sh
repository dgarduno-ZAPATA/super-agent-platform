#!/usr/bin/env bash
set -euo pipefail

SYNC_DATABASE_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"

alembic upgrade head
psql "$SYNC_DATABASE_URL" -c "
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
"
