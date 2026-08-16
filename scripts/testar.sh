#!/usr/bin/env bash
# Suíte completa em Docker, isolada e descartável.
#
#   ./scripts/testar.sh              tudo
#   ./scripts/testar.sh -k rls       filtra (argumentos vão para o pytest)
#
# Sobe um Postgres+PostGIS em tmpfs com nome de projeto próprio, aplica as
# migrations, roda os testes e derruba tudo. Não toca o banco de desenvolvimento.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f compose.test.yaml"

if ! docker info >/dev/null 2>&1; then
  echo "docker não está acessível. No WSL: inicie o Docker Desktop e habilite a" >&2
  echo "integração para esta distro, ou instale o engine nativo:" >&2
  echo "  sudo apt-get install -y docker.io && sudo systemctl enable --now docker" >&2
  echo "  sudo usermod -aG docker \$USER   # e reabra o shell" >&2
  exit 1
fi

limpar() { $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true; }
trap limpar EXIT

limpar
$COMPOSE build --quiet
$COMPOSE run --rm tests pytest -q "$@"
