#!/bin/bash
# Papel da aplicação. Roda uma vez, no initdb do contêiner.
#
# POR QUE ISTO EXISTE: no PostgreSQL, superusuários e papéis com BYPASSRLS ignoram
# row-level security por completo, e FORCE ROW LEVEL SECURITY só sujeita o *dono*
# da tabela — não um superusuário. A imagem oficial do Postgres cria POSTGRES_USER
# como superusuário. Se a aplicação conectar com esse papel, toda a RLS do projeto
# é decoração: nenhuma política chega a ser avaliada.
#
# Dois papéis, de propósito:
#   POSTGRES_USER  dono/superusuário — só migrations e administração
#   clima_app      NOSUPERUSER, NOBYPASSRLS — é quem a aplicação usa
#
# O teste test_integracao_rls.py::test_papel_app_nao_ignora_rls faz um deploy mal
# configurado falhar alto, em vez de vazar dados entre tenants em silêncio.
#
# É um script .sh e não .sql porque o entrypoint do Postgres só expande variáveis
# de ambiente nos .sh. Evite apóstrofo em CLIMA_APP_PASSWORD.
set -euo pipefail

if [ -z "${CLIMA_APP_PASSWORD:-}" ]; then
  echo "ERRO: CLIMA_APP_PASSWORD não definida — o papel da aplicação não seria criado" >&2
  exit 1
fi

existe=$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'clima_app'" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")

if [ "$existe" != "1" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
    "CREATE ROLE clima_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
     PASSWORD '${CLIMA_APP_PASSWORD}'"
  echo "papel clima_app criado"
else
  echo "papel clima_app já existe"
fi
