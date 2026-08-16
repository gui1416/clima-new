"""correlacao: vínculos par-a-par, eventos canônicos e divergência preservada

Revision ID: 005_correlacao
Revises: 004_source_records
Create Date: 2026-08-16

Fase 2 — o diferencial. Quatro decisões que o esquema materializa.

── Divergência é produto, não ruído ──────────────────────────────────────────

``event_field_claims`` guarda o que **cada** fonte afirma sobre **cada** campo. Sem
essa tabela o produto viraria mais um consolidador que esconde discordância, que é
exatamente o problema que ele existe para resolver. O painel de procedência lê
daqui.

── Precedência por campo, nunca média ────────────────────────────────────────

A síntese escolhe o valor de uma fonte por campo. Média de magnitudes de duas
redes sismográficas não é uma magnitude: é um número que ninguém mediu.

── Parâmetros de blocking em tabela ──────────────────────────────────────────

Raio, janela e limiares vivem em ``correlation_params``, por tipo de evento,
porque a física de cada um é diferente e porque calibrar não deveria exigir
deploy. Um terremoto tem epicentro incerto e horário preciso; uma enchente é o
contrário.

── Falso merge é pior que falso split ────────────────────────────────────────

Unir dois eventos distintos **esconde** um evento real; deixar duplicatas apenas
repete informação. Daí dois limiares: acima de ``limiar_uniao`` une, entre ele e
``limiar_duvida`` marca ``incerto`` e vai para revisão humana. E daí a guarda de
diâmetro: cluster que estoura a extensão do tipo não é fundido em silêncio.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005_correlacao"
down_revision = "004_source_records"
branch_labels = None
depends_on = None

PAPEL = "clima_app"


def upgrade() -> None:
    # ── parâmetros por tipo ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE correlation_params (
          event_type       text PRIMARY KEY,
          raio_m           int  NOT NULL CHECK (raio_m > 0),
          janela_seg       int  NOT NULL CHECK (janela_seg > 0),
          peso_espaco      real NOT NULL,
          peso_tempo       real NOT NULL,
          peso_metrica     real NOT NULL,
          peso_toponimo    real NOT NULL,
          intercepto       real NOT NULL,
          limiar_uniao     real NOT NULL CHECK (limiar_uniao BETWEEN 0 AND 1),
          limiar_duvida    real NOT NULL CHECK (limiar_duvida BETWEEN 0 AND 1),
          diametro_max_m   int  NOT NULL,
          diametro_max_seg int  NOT NULL,
          observacao       text,
          CHECK (limiar_duvida <= limiar_uniao)
        )
        """
    )

    op.bulk_insert(
        sa.table(
            "correlation_params",
            *[
                sa.column(c)
                for c in (
                    "event_type raio_m janela_seg peso_espaco peso_tempo peso_metrica "
                    "peso_toponimo intercepto limiar_uniao limiar_duvida diametro_max_m "
                    "diametro_max_seg observacao"
                ).split()
            ],
        ),
        [
            {
                "event_type": "earthquake",
                # Epicentro varia entre redes; o horário de origem é preciso e é o
                # que discrimina. Daí janela apertada e raio generoso.
                "raio_m": 100_000,
                "janela_seg": 90,
                "peso_espaco": -4.0,
                "peso_tempo": -5.5,
                "peso_metrica": -3.0,
                # Topônimo é sinal fraco e traiçoeiro: nomes divergem entre idiomas
                # e duas cidades homônimas existem. Peso baixo de propósito.
                "peso_toponimo": 0.8,
                "intercepto": 5.2,
                "limiar_uniao": 0.90,
                "limiar_duvida": 0.60,
                "diametro_max_m": 150_000,
                "diametro_max_seg": 120,
                "observacao": "Calibração inicial; recalibrar com golden set real (portão G2).",
            },
            {
                "event_type": "cyclone",
                # Boletins saem em horários sinóticos de 6 h, então a posição
                # precisa ser interpolada antes de comparar.
                "raio_m": 200_000,
                "janela_seg": 3 * 3600,
                "peso_espaco": -3.0,
                "peso_tempo": -2.0,
                "peso_metrica": -2.0,
                "peso_toponimo": 1.2,
                "intercepto": 4.0,
                "limiar_uniao": 0.90,
                "limiar_duvida": 0.60,
                "diametro_max_m": 400_000,
                "diametro_max_seg": 6 * 3600,
                "observacao": "Sem conector ainda. Parâmetros do §5.1 do plano.",
            },
            {
                "event_type": "flood",
                # Evento lento e areal; "início" é definição editorial de cada fonte.
                "raio_m": 50_000,
                "janela_seg": 24 * 3600,
                "peso_espaco": -5.0,
                "peso_tempo": -1.2,
                "peso_metrica": -1.0,
                "peso_toponimo": 2.0,
                "intercepto": 3.5,
                "limiar_uniao": 0.90,
                "limiar_duvida": 0.55,
                "diametro_max_m": 120_000,
                "diametro_max_seg": 48 * 3600,
                "observacao": "Sem conector ainda.",
            },
        ],
    )

    # ── vínculos par-a-par, auditáveis ──────────────────────────────────────
    op.execute(
        """
        CREATE TABLE record_links (
          a_id         bigint NOT NULL REFERENCES source_records(id),
          b_id         bigint NOT NULL REFERENCES source_records(id),
          tenant_id    uuid   NOT NULL REFERENCES tenants(id),
          metodo       text   NOT NULL CHECK (metodo IN ('xref','probabilistico','manual')),
          veredito     text   NOT NULL CHECK (veredito IN ('mesmo','distinto','incerto')),
          score        real,
          -- O vetor de features fica gravado: é o que permite explicar na interface
          -- por que dois registros foram unidos, e recalibrar sem reprocessar.
          features     jsonb  NOT NULL DEFAULT '{}'::jsonb,
          decidido_em  timestamptz NOT NULL DEFAULT now(),
          decidido_por text,
          PRIMARY KEY (a_id, b_id),
          -- Par canônico ordenado: evita guardar (a,b) e (b,a) como coisas distintas.
          CHECK (a_id < b_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_record_links_veredito ON record_links (veredito, score DESC)")
    op.execute("CREATE INDEX ix_record_links_b ON record_links (b_id)")

    # ── evento canônico e seu histórico append-only ─────────────────────────
    op.execute(
        """
        CREATE TABLE canonical_events (
          id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id   uuid NOT NULL REFERENCES tenants(id),
          event_type  text NOT NULL,
          first_seen  timestamptz NOT NULL,
          last_seen   timestamptz NOT NULL,
          -- Rótulo legível, derivado da observação mais antiga do cluster. NÃO é a
          -- identidade: a identidade é `id`, resolvida pelos membros. Um cluster_key
          -- por ordem alfabética de fonte trocava de valor quando entrava membro de
          -- fonte "menor", criando evento novo e orfanando o histórico do anterior.
          cluster_key text NOT NULL,
          -- Quando dois eventos canônicos separados passam a ser reconhecidos como o
          -- mesmo, o mais antigo sobrevive e o outro aponta para cá. Preservar em vez
          -- de apagar mantém o histórico, que é o princípio 2.
          fundido_em  uuid REFERENCES canonical_events(id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE canonical_event_snapshots (
          canonical_event_id uuid NOT NULL REFERENCES canonical_events(id) ON DELETE CASCADE,
          seq                int  NOT NULL,
          valid_from         timestamptz NOT NULL DEFAULT now(),
          geom               geography(Point, 4326) NOT NULL,
          observed_at        timestamptz NOT NULL,
          lugar              text,
          magnitude          real,
          profundidade_km    real,
          metrics            jsonb NOT NULL DEFAULT '{}'::jsonb,
          source_count       int  NOT NULL,
          confianca          real NOT NULL,
          status             text NOT NULL,
          -- 'nova_fonte' | 'magnitude_revisada' | 'primeira_observacao' | ...
          motivo_mudanca     text NOT NULL,
          PRIMARY KEY (canonical_event_id, seq)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE canonical_event_membros (
          canonical_event_id uuid   NOT NULL REFERENCES canonical_events(id) ON DELETE CASCADE,
          source_record_id   bigint NOT NULL REFERENCES source_records(id),
          source_id          text   NOT NULL REFERENCES sources(id),
          PRIMARY KEY (canonical_event_id, source_record_id)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_membro_registro ON canonical_event_membros (source_record_id)"
    )

    # ── a divergência, preservada ───────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE event_field_claims (
          canonical_event_id uuid   NOT NULL REFERENCES canonical_events(id) ON DELETE CASCADE,
          campo              text   NOT NULL,
          source_id          text   NOT NULL REFERENCES sources(id),
          valor              jsonb  NOT NULL,
          source_record_id   bigint NOT NULL REFERENCES source_records(id),
          -- Se este é o valor que a síntese adotou para o campo.
          vencedor           boolean NOT NULL DEFAULT false,
          PRIMARY KEY (canonical_event_id, campo, source_id)
        )
        """
    )

    # ── estado atual do evento canônico ─────────────────────────────────────
    op.execute(
        """
        CREATE VIEW v_eventos_canonicos WITH (security_invoker = true) AS
        SELECT DISTINCT ON (e.id)
               e.id, e.tenant_id, e.event_type, e.first_seen, e.last_seen, e.cluster_key,
               s.seq, s.geom, s.observed_at, s.lugar, s.magnitude, s.profundidade_km,
               s.metrics, s.source_count, s.confianca, s.status, s.motivo_mudanca,
               s.valid_from AS atualizado_em,
               clima_severidade_sismo(s.magnitude) AS severidade,
               (SELECT count(*) FROM canonical_event_snapshots h
                  WHERE h.canonical_event_id = e.id) AS snapshots,
               (SELECT array_agg(DISTINCT m.source_id ORDER BY m.source_id)
                  FROM canonical_event_membros m WHERE m.canonical_event_id = e.id) AS fontes
        FROM canonical_events e
        JOIN canonical_event_snapshots s ON s.canonical_event_id = e.id
        -- Evento absorvido por outro sai do estado atual, mas continua no banco.
        WHERE e.fundido_em IS NULL
        ORDER BY e.id, s.seq DESC
        """
    )

    # Fila de revisão: o que o motor não teve confiança de unir. Existir é a
    # diferença entre admitir dúvida e fundir errado em silêncio.
    op.execute(
        """
        CREATE VIEW v_revisao_pendente WITH (security_invoker = true) AS
        SELECT l.a_id, l.b_id, l.score, l.features, l.metodo, l.decidido_em,
               a.source_id AS fonte_a, a.source_event_id AS evento_a, a.magnitude AS mag_a,
               b.source_id AS fonte_b, b.source_event_id AS evento_b, b.magnitude AS mag_b,
               ST_Distance(a.geom, b.geom) AS distancia_m,
               abs(extract(epoch FROM a.observed_at - b.observed_at)) AS delta_seg
        FROM record_links l
        JOIN source_records a ON a.id = l.a_id
        JOIN source_records b ON b.id = l.b_id
        WHERE l.veredito = 'incerto'
        ORDER BY l.score DESC
        """
    )

    # ── privilégios e RLS ───────────────────────────────────────────────────
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
            RAISE WARNING 'papel {PAPEL} não existe; privilégios da Fase 2 não aplicados';
            RETURN;
          END IF;
          EXECUTE 'GRANT SELECT ON correlation_params TO {PAPEL}';
          -- O motor reconstrói cluster quando chega membro novo, então aqui há
          -- UPDATE e DELETE — ao contrário de source_records, que é observação.
          EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON record_links TO {PAPEL}';
          EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON canonical_events TO {PAPEL}';
          EXECUTE 'GRANT SELECT, INSERT, DELETE ON canonical_event_snapshots TO {PAPEL}';
          EXECUTE 'GRANT SELECT, INSERT, DELETE ON canonical_event_membros TO {PAPEL}';
          EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON event_field_claims TO {PAPEL}';
          EXECUTE 'GRANT SELECT ON v_eventos_canonicos TO {PAPEL}';
          EXECUTE 'GRANT SELECT ON v_revisao_pendente TO {PAPEL}';
        END $$
        """
    )

    for tabela in (
        "record_links",
        "canonical_events",
        "event_field_claims",
    ):
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
            if tabela != "event_field_claims"
            else f"""
            CREATE POLICY {tabela}_leitura ON {tabela} FOR SELECT
            USING (clima_current_tenant() IS NOT NULL)
            """
        )
        # Uma política por comando que a tabela usa — a lição da migration 003:
        # comando sem política não erra, apenas não afeta linha nenhuma.
        for cmd, clausula in (
            ("INSERT", "WITH CHECK (true)"),
            ("UPDATE", "USING (true) WITH CHECK (true)"),
            ("DELETE", "USING (true)"),
        ):
            if tabela == "canonical_events" and cmd == "INSERT":
                clausula = "WITH CHECK (tenant_id = clima_current_tenant())"
            op.execute(
                f"CREATE POLICY {tabela}_{cmd.lower()} ON {tabela} FOR {cmd} {clausula}"
            )


def downgrade() -> None:
    for v in ("v_revisao_pendente", "v_eventos_canonicos"):
        op.execute(f"DROP VIEW IF EXISTS {v}")
    for t in (
        "event_field_claims",
        "canonical_event_membros",
        "canonical_event_snapshots",
        "canonical_events",
        "record_links",
        "correlation_params",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t}")
