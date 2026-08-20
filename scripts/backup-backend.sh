#!/usr/bin/env bash
set -euo pipefail

destino=${1:-./backups}
mkdir -p "$destino"
arquivo="$destino/clima-$(date -u +%Y%m%dT%H%M%SZ).dump"

docker compose exec -T db pg_dump \
  --username "${POSTGRES_USER:-clima_owner}" \
  --dbname "${POSTGRES_DB:-clima}" \
  --format=custom --compress=9 > "$arquivo"

echo "$arquivo"
