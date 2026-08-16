"""source_records: o payload bruto vira observação normalizada

Revision ID: 004_source_records
Revises: 003_politicas_rls
Create Date: 2026-08-16

Fase 1 do plano. Três decisões que merecem explicação.

── `source_updated_at` em vez de `revision` ──────────────────────────────────

O esboço do plano previa `revision int` com unique em
``(source_id, source_event_id, revision)``. Trocado por
``(source_id, source_event_id, source_updated_at)``.

O USGS já versiona: cada feature traz ``properties.updated``, que muda quando a
rede revisa magnitude, profundidade ou epicentro. Esse campo **é** o marcador de
revisão da fonte. Um contador próprio precisaria ser calculado a partir da
contagem de linhas existentes, o que introduz corrida entre workers e não carrega
nenhuma informação que `updated` já não carregue. O estado atual é a linha de
maior `source_updated_at`, e o histórico é append-only como manda o princípio 2.

── Progresso de parse fora de `raw_payloads` ─────────────────────────────────

Marcar "já analisado" numa coluna de `raw_payloads` exigiria UPDATE naquela
tabela, que é imutável por privilégio negado (migration 002). Daí `parse_runs`:
um registro por payload analisado, com o que saiu e o que falhou. Pendente é
``raw_payloads`` sem `parse_runs` correspondente — o que também dá replay de
graça: apagar uma linha de `parse_runs` reprocessa aquele payload.

── Severidade é função de uma métrica, não score composto ────────────────────

``clima_severidade_sismo`` faz o banding de **uma** grandeza física (magnitude)
para o vocabulário visual do protótipo. Isso não é o score composto que o
CLAUDE.md restringe: não há equivalência entre categorias, não há peso arbitrário
entre grandezas incomensuráveis. É uma partição monotônica de um único eixo, e a
magnitude viaja junto em toda resposta da API.

Fica em SQL, e não em Python, para haver uma definição só — mudar limiar é
migration, não deploy silencioso.
"""

from __future__ import annotations

from alembic import op

revision = "004_source_records"
down_revision = "003_politicas_rls"
branch_labels = None
depends_on = None

PAPEL = "clima_app"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE source_records (
          id                bigserial PRIMARY KEY,
          tenant_id         uuid NOT NULL REFERENCES tenants(id),
          source_id         text NOT NULL REFERENCES sources(id),
          source_event_id   text NOT NULL,

          -- Rastro até o byte cru que originou esta linha. A FK é composta porque
          -- raw_payloads é particionada e sua PK inclui a chave de partição.
          raw_payload_id    bigint NOT NULL,
          raw_fetched_at    timestamptz NOT NULL,

          observed_at       timestamptz NOT NULL,   -- quando o fenômeno ocorreu
          source_updated_at timestamptz NOT NULL,   -- revisão declarada pela fonte
          ingested_at       timestamptz NOT NULL DEFAULT now(),

          event_type        text NOT NULL,
          geom              geography(Point, 4326) NOT NULL,
          lugar             text,
          magnitude         real,
          profundidade_km   real,

          -- Numéricas soltas da fonte (nst, gap, rms, sig, mmi…). Ficam em jsonb
          -- porque variam por fonte e não são filtradas.
          metrics           jsonb NOT NULL DEFAULT '{}'::jsonb,
          -- Identificadores cruzados: a via determinística do §5.2 do plano.
          xrefs             jsonb NOT NULL DEFAULT '{}'::jsonb,
          status            text NOT NULL,

          CONSTRAINT fk_source_records_raw
            FOREIGN KEY (raw_payload_id, raw_fetched_at)
            REFERENCES raw_payloads (id, fetched_at),
          CONSTRAINT uq_source_records_revisao
            UNIQUE (source_id, source_event_id, source_updated_at)
        )
        """
    )
    op.execute("CREATE INDEX ix_source_records_geom ON source_records USING GIST (geom)")
    op.execute("CREATE INDEX ix_source_records_observed ON source_records USING BRIN (observed_at)")
    op.execute(
        "CREATE INDEX ix_source_records_evento ON source_records "
        "(source_id, source_event_id, source_updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_source_records_magnitude ON source_records (magnitude DESC) "
        "WHERE magnitude IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE parse_runs (
          raw_payload_id bigint NOT NULL,
          raw_fetched_at timestamptz NOT NULL,
          tenant_id      uuid NOT NULL REFERENCES tenants(id),
          source_id      text NOT NULL REFERENCES sources(id),
          parsed_at      timestamptz NOT NULL DEFAULT now(),
          registros_novos int NOT NULL DEFAULT 0,
          registros_vistos int NOT NULL DEFAULT 0,
          erro           text,
          PRIMARY KEY (raw_payload_id, raw_fetched_at),
          CONSTRAINT fk_parse_runs_raw
            FOREIGN KEY (raw_payload_id, raw_fetched_at)
            REFERENCES raw_payloads (id, fetched_at)
        )
        """
    )

    # ── severidade a partir da magnitude ────────────────────────────────────
    # Limiares alinhados às faixas usuais de percepção e dano: M≥6,0 é onde dano
    # estrutural fica provável em área povoada; M≥4,5 é sentido amplamente e é o
    # piso de relevância operacional do USGS para eventos globais.
    op.execute(
        """
        CREATE FUNCTION clima_severidade_sismo(mag real) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
          SELECT CASE
            WHEN mag IS NULL  THEN 'moderate'
            WHEN mag >= 6.0   THEN 'critical'
            WHEN mag >= 4.5   THEN 'high'
            ELSE 'moderate'
          END
        $$
        """
    )

    # ── estado atual: a última revisão de cada evento de cada fonte ─────────
    # É view sobre o append-only, nunca linha mutável (princípio 2).
    op.execute(
        """
        CREATE VIEW v_registros_atuais WITH (security_invoker = true) AS
        SELECT DISTINCT ON (r.source_id, r.source_event_id)
               r.id, r.tenant_id, r.source_id, r.source_event_id,
               r.observed_at, r.source_updated_at, r.ingested_at,
               r.event_type, r.geom, r.lugar, r.magnitude, r.profundidade_km,
               r.metrics, r.xrefs, r.status,
               clima_severidade_sismo(r.magnitude) AS severidade,
               -- Quantas revisões desta fonte para este evento já vimos.
               (SELECT count(*) FROM source_records h
                 WHERE h.source_id = r.source_id
                   AND h.source_event_id = r.source_event_id) AS revisoes,
               s.redistribuicao,
               s.atribuicao_exigida
        FROM source_records r
        JOIN sources s ON s.id = r.source_id
        ORDER BY r.source_id, r.source_event_id, r.source_updated_at DESC
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
            RAISE WARNING 'papel {PAPEL} não existe; privilégios da Fase 1 não aplicados';
            RETURN;
          END IF;
          -- source_records é observação: insere e lê, nunca altera nem remove.
          EXECUTE 'GRANT SELECT, INSERT ON source_records TO {PAPEL}';
          EXECUTE 'GRANT USAGE ON SEQUENCE source_records_id_seq TO {PAPEL}';
          -- parse_runs é log de progresso; DELETE é o mecanismo de replay.
          EXECUTE 'GRANT SELECT, INSERT, DELETE ON parse_runs TO {PAPEL}';
          EXECUTE 'GRANT SELECT ON v_registros_atuais TO {PAPEL}';
          EXECUTE 'GRANT EXECUTE ON FUNCTION clima_severidade_sismo(real) TO {PAPEL}';
        END $$
        """
    )

    # ── RLS, com as mesmas políticas por comando da 003 ─────────────────────
    for tabela in ("source_records", "parse_runs"):
        op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {tabela}_leitura ON {tabela} FOR SELECT
            USING (
              clima_current_tenant() IS NOT NULL
              AND (tenant_id = clima_current_tenant() OR tenant_id = clima_system_tenant())
            )
            """
        )
        op.execute(
            f"""
            CREATE POLICY {tabela}_escrita ON {tabela} FOR INSERT
            WITH CHECK (tenant_id = clima_current_tenant())
            """
        )

    # parse_runs precisa de DELETE para replay; source_records, não.
    op.execute(
        """
        CREATE POLICY parse_runs_remocao ON parse_runs FOR DELETE
        USING (tenant_id = clima_current_tenant())
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_registros_atuais")
    op.execute("DROP TABLE IF EXISTS parse_runs")
    op.execute("DROP TABLE IF EXISTS source_records")
    op.execute("DROP FUNCTION IF EXISTS clima_severidade_sismo(real)")
