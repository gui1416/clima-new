#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "uso: $0 caminho/backup.dump" >&2
  exit 2
fi

container="clima-restore-$RANDOM-$RANDOM"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$container" \
  -e POSTGRES_PASSWORD=restore -e POSTGRES_DB=restore postgis/postgis:16-3.4 >/dev/null
until docker exec "$container" pg_isready -U postgres -d restore >/dev/null 2>&1; do
  sleep 1
done
docker exec -i "$container" pg_restore -U postgres -d restore --clean --if-exists < "$1"
docker exec "$container" psql -U postgres -d restore -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) AS fontes FROM sources; SELECT count(*) AS eventos FROM canonical_events;"
