"""fundacao: tenants, RLS, registro de fontes, payload_raw particionado

Revision ID: 001_fundacao
Revises:
Create Date: 2026-08-16

Esta migration carrega quatro decisões estruturais que são caras de retrofitar:

1. ``tenant_id`` e RLS *forçada* desde já, com um tenant de sistema para o
   pipeline compartilhado de ingestão.
2. ``payload_raw`` imutável e particionado por mês, com partição DEFAULT como
   rede de segurança — uma partição faltante nunca deve fazer uma coleta falhar.
3. Corpo do payload endereçado por conteúdo, deduplicado por sha256.
4. ``sources.redistribuicao`` como trava de licença, não como anotação.

O DDL é escrito à mão. Não use ``alembic revision --autogenerate`` para alterar
estas tabelas: particionamento, RLS e a partição DEFAULT não são representáveis
nos modelos e o autogenerate tentaria desfazê-los.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "001_fundacao"
down_revision = None
branch_labels = None
depends_on = None

TENANT_SISTEMA = "00000000-0000-0000-0000-000000000001"
PARTICOES_INICIAIS = 3  # mês corrente + 2 à frente


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ── contexto de tenant ──────────────────────────────────────────────────
    # Fail-closed: GUC ausente devolve NULL, e NULL = uuid nunca é verdadeiro,
    # então uma sessão sem tenant não vê linha nenhuma.
    op.execute(
        """
        CREATE FUNCTION clima_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE AS $$
          SELECT nullif(current_setting('clima.tenant_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION clima_system_tenant() RETURNS uuid
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
          SELECT '{TENANT_SISTEMA}'::uuid
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE tenants (
          id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          nome      text NOT NULL,
          criado_em timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"INSERT INTO tenants (id, nome) VALUES ('{TENANT_SISTEMA}', 'Sistema — pipeline compartilhado')"
    )

    # ── registro de fontes ──────────────────────────────────────────────────
    # Global e sem RLS: é catálogo de conectores, não dado de cliente.
    op.execute(
        """
        CREATE TABLE sources (
          id                 text PRIMARY KEY,
          nome               text NOT NULL,
          redistribuicao     text NOT NULL
            CHECK (redistribuicao IN ('livre','atribuicao','interna')),
          atribuicao_exigida text,
          intervalo_poll_seg smallint NOT NULL CHECK (intervalo_poll_seg > 0),
          ativa              boolean NOT NULL DEFAULT true,
          observacao         text
        )
        """
    )

    # 'interna' é o padrão seguro para o que não está resolvido: a fonte entra na
    # correlação e no cálculo de confiança, mas seu payload nunca é serializado.
    # Só sai de 'interna' com resposta por escrito (portão G4 do plano).
    op.bulk_insert(
        sa.table(
            "sources",
            sa.column("id", sa.Text),
            sa.column("nome", sa.Text),
            sa.column("redistribuicao", sa.Text),
            sa.column("atribuicao_exigida", sa.Text),
            sa.column("intervalo_poll_seg", sa.SmallInteger),
            sa.column("ativa", sa.Boolean),
            sa.column("observacao", sa.Text),
        ),
        [
            {
                "id": "usgs",
                "nome": "USGS — Earthquake Hazards Program",
                "redistribuicao": "livre",
                "atribuicao_exigida": None,
                "intervalo_poll_seg": 60,
                "ativa": True,
                "observacao": "Obra do governo dos EUA, domínio público.",
            },
            {
                "id": "noaa",
                "nome": "NOAA / NWS — alertas e ciclones",
                "redistribuicao": "livre",
                "atribuicao_exigida": None,
                "intervalo_poll_seg": 300,
                "ativa": False,
                "observacao": "Domínio público. Entra na Fase 5.",
            },
            {
                "id": "nasa_eonet",
                "nome": "NASA EONET",
                "redistribuicao": "atribuicao",
                "atribuicao_exigida": "Fonte: NASA EONET",
                "intervalo_poll_seg": 3600,
                "ativa": False,
                "observacao": "Traz array de fontes com link ao boletim original — cruzamento gratuito.",
            },
            {
                "id": "nasa_firms",
                "nome": "NASA FIRMS — focos de calor",
                "redistribuicao": "atribuicao",
                "atribuicao_exigida": "Fonte: NASA FIRMS",
                "intervalo_poll_seg": 900,
                "ativa": False,
                "observacao": "Entrega pixels, não eventos. Exige clustering na ingestão (§5.6).",
            },
            {
                "id": "gdacs",
                "nome": "GDACS — Global Disaster Alert and Coordination System",
                "redistribuicao": "atribuicao",
                "atribuicao_exigida": "Fonte: GDACS (Comissão Europeia / JRC)",
                "intervalo_poll_seg": 900,
                "ativa": False,
                "observacao": "Reuso da CE presume atribuição; CONFIRMAR termos antes do tier pago.",
            },
            {
                "id": "copernicus_ems",
                "nome": "Copernicus Emergency Management Service",
                "redistribuicao": "interna",
                "atribuicao_exigida": None,
                "intervalo_poll_seg": 3600,
                "ativa": False,
                "observacao": "BLOQUEIO G4: licença pode proibir revenda. Só enriquecimento interno.",
            },
            {
                "id": "inmet",
                "nome": "INMET — Instituto Nacional de Meteorologia",
                "redistribuicao": "interna",
                "atribuicao_exigida": None,
                "intervalo_poll_seg": 600,
                "ativa": False,
                "observacao": "BLOQUEIO G4: termos próprios. Só enriquecimento interno.",
            },
        ],
    )

    # ── log de coletas ──────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE ingest_runs (
          id              bigserial PRIMARY KEY,
          tenant_id       uuid NOT NULL REFERENCES tenants(id),
          source_id       text NOT NULL REFERENCES sources(id),
          started_at      timestamptz NOT NULL DEFAULT now(),
          finished_at     timestamptz,
          url             text,
          http_status     smallint,
          resultado       text CHECK (resultado IN ('ok','nao_modificado','erro')),
          erro            text,
          bytes_recebidos bigint,
          body_sha256     bytea,
          etag            text,
          last_modified   text,
          CHECK (finished_at IS NULL OR finished_at >= started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_ingest_runs_source_started ON ingest_runs (source_id, started_at DESC)"
    )

    # ── corpo do payload, endereçado por conteúdo ───────────────────────────
    # Única tabela do pipeline sem tenant_id, deliberadamente: a deduplicação por
    # sha256 é o ponto da tabela, e um mesmo corpo do USGS é literalmente o mesmo
    # byte para todos os tenants. O corpo só é alcançável via raw_payloads, que é
    # tenant-scoped; a API nunca expõe leitura por sha256.
    op.execute(
        """
        CREATE TABLE payload_bodies (
          sha256        bytea PRIMARY KEY CHECK (length(sha256) = 32),
          body          bytea NOT NULL,
          bytes_total   bigint NOT NULL,
          content_type  text,
          first_seen_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ── payload_raw: uma linha por coleta, particionada por mês ─────────────
    op.execute(
        """
        CREATE TABLE raw_payloads (
          id            bigserial,
          fetched_at    timestamptz NOT NULL DEFAULT now(),
          tenant_id     uuid NOT NULL REFERENCES tenants(id),
          source_id     text NOT NULL REFERENCES sources(id),
          ingest_run_id bigint NOT NULL REFERENCES ingest_runs(id),
          url           text NOT NULL,
          http_status   smallint NOT NULL,
          headers       jsonb NOT NULL DEFAULT '{}'::jsonb,
          body_sha256   bytea NOT NULL REFERENCES payload_bodies(sha256),
          PRIMARY KEY (id, fetched_at)
        ) PARTITION BY RANGE (fetched_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_raw_payloads_source_fetched ON raw_payloads (source_id, fetched_at DESC)"
    )
    op.execute("CREATE INDEX ix_raw_payloads_body ON raw_payloads (body_sha256)")

    op.execute(
        """
        CREATE FUNCTION clima_ensure_raw_partition(p_mes date) RETURNS text
        LANGUAGE plpgsql AS $$
        DECLARE
          v_ini  date := date_trunc('month', p_mes)::date;
          v_fim  date := (date_trunc('month', p_mes) + interval '1 month')::date;
          v_nome text := format('raw_payloads_%s', to_char(v_ini, 'YYYY_MM'));
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = v_nome AND n.nspname = current_schema()
          ) THEN
            EXECUTE format(
              'CREATE TABLE %I PARTITION OF raw_payloads FOR VALUES FROM (%L) TO (%L)',
              v_nome, v_ini, v_fim);
          END IF;
          RETURN v_nome;
        END $$
        """
    )

    # Rede de segurança. Sem ela, um mês sem partição faz o INSERT falhar e a
    # coleta é perdida — que é exatamente o único erro irrecuperável do projeto.
    # O custo é conhecido: enquanto houver linha aqui, criar a partição do mês
    # correspondente falha até que as linhas sejam movidas. Por isso existe
    # v_alarme_particao_default, e o job de partições roda com 2 meses de folga.
    op.execute("CREATE TABLE raw_payloads_default PARTITION OF raw_payloads DEFAULT")

    mes_atual = date.today().replace(day=1)
    for i in range(PARTICOES_INICIAIS):
        op.execute(
            sa.text("SELECT clima_ensure_raw_partition(:m)").bindparams(
                m=_add_meses(mes_atual, i)
            )
        )

    # ── RLS ─────────────────────────────────────────────────────────────────
    # FORCE porque o dono da tabela ignora RLS por padrão, e a aplicação conecta
    # como dono na v1. Leitura enxerga o próprio tenant mais o de sistema (o
    # pipeline compartilhado); escrita só o próprio.
    for tabela in ("ingest_runs", "raw_payloads"):
        op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {tabela}_leitura ON {tabela} FOR SELECT
            USING (tenant_id = clima_current_tenant()
                   OR tenant_id = clima_system_tenant())
            """
        )
        op.execute(
            f"""
            CREATE POLICY {tabela}_escrita ON {tabela} FOR INSERT
            WITH CHECK (tenant_id = clima_current_tenant())
            """
        )

    # ── continuidade da coleta ──────────────────────────────────────────────
    # security_invoker para que as views respeitem a RLS de quem consulta, e não
    # a do dono. Sem isso, uma view seria um furo silencioso no isolamento.
    op.execute(
        """
        CREATE VIEW v_lacunas_coleta WITH (security_invoker = true) AS
        WITH ordenadas AS (
          SELECT source_id, started_at,
                 lag(started_at) OVER (PARTITION BY source_id ORDER BY started_at) AS anterior
          FROM ingest_runs
          WHERE resultado IN ('ok','nao_modificado')
        )
        SELECT source_id,
               anterior              AS de,
               started_at            AS ate,
               started_at - anterior AS duracao
        FROM ordenadas
        WHERE anterior IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE VIEW v_saude_fontes WITH (security_invoker = true) AS
        SELECT s.id AS source_id, s.nome, s.ativa, s.redistribuicao,
               s.intervalo_poll_seg,
               max(r.started_at) FILTER (WHERE r.resultado IN ('ok','nao_modificado'))
                 AS ultima_coleta_ok,
               max(r.started_at) FILTER (WHERE r.resultado = 'erro') AS ultimo_erro_em,
               count(*) FILTER (WHERE r.resultado = 'erro'
                                AND r.started_at > now() - interval '1 hour')
                 AS erros_1h
        FROM sources s
        LEFT JOIN ingest_runs r ON r.source_id = s.id
        GROUP BY s.id, s.nome, s.ativa, s.redistribuicao, s.intervalo_poll_seg
        """
    )

    op.execute(
        """
        CREATE VIEW v_alarme_particao_default WITH (security_invoker = true) AS
        SELECT count(*) AS linhas, min(fetched_at) AS mais_antiga, max(fetched_at) AS mais_nova
        FROM raw_payloads_default
        """
    )


def _add_meses(d: date, n: int) -> date:
    mes = d.month - 1 + n
    return date(d.year + mes // 12, mes % 12 + 1, 1)


def downgrade() -> None:
    for v in ("v_alarme_particao_default", "v_saude_fontes", "v_lacunas_coleta"):
        op.execute(f"DROP VIEW IF EXISTS {v}")
    op.execute("DROP TABLE IF EXISTS raw_payloads")  # leva as partições
    op.execute("DROP TABLE IF EXISTS payload_bodies")
    op.execute("DROP TABLE IF EXISTS ingest_runs")
    op.execute("DROP TABLE IF EXISTS sources")
    op.execute("DROP TABLE IF EXISTS tenants")
    op.execute("DROP FUNCTION IF EXISTS clima_ensure_raw_partition(date)")
    op.execute("DROP FUNCTION IF EXISTS clima_system_tenant()")
    op.execute("DROP FUNCTION IF EXISTS clima_current_tenant()")
