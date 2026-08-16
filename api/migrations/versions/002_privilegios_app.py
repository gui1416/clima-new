"""privilegios: papel da aplicação recebe o mínimo, e não é superusuário

Revision ID: 002_privilegios_app
Revises: 001_fundacao
Create Date: 2026-08-16

Separada da 001 porque depende de um papel criado fora do Alembic (no initdb do
contêiner, ver ``api/db/init/10-papel-app.sh``). Os GRANTs são condicionais: num
Postgres gerenciado onde ``clima_app`` ainda não exista, a migration passa e
avisa em vez de falhar.

A razão de existir está no script de init: superusuário ignora RLS, então a
aplicação precisa de um papel comum. Esta migration dá a esse papel exatamente o
que o pipeline da Fase 0 usa, e nada além.
"""

from __future__ import annotations

from alembic import op

revision = "002_privilegios_app"
down_revision = "001_fundacao"
branch_labels = None
depends_on = None

PAPEL = "clima_app"

GRANTS = [
    "GRANT USAGE ON SCHEMA public TO {p}",
    # Registro de fontes: só leitura. O conector não mexe no catálogo.
    "GRANT SELECT ON sources TO {p}",
    # Log de coletas: é a única tabela que a aplicação atualiza (abre antes do
    # fetch, fecha depois).
    "GRANT SELECT, INSERT, UPDATE ON ingest_runs TO {p}",
    # payload_raw: escreve e lê, nunca altera nem remove. A ausência de
    # UPDATE/DELETE aqui é a garantia de imutabilidade no nível de privilégio,
    # não só de disciplina.
    "GRANT SELECT, INSERT ON payload_bodies TO {p}",
    "GRANT SELECT, INSERT ON raw_payloads TO {p}",
    "GRANT USAGE ON SEQUENCE ingest_runs_id_seq TO {p}",
    "GRANT USAGE ON SEQUENCE raw_payloads_id_seq TO {p}",
    "GRANT SELECT ON v_lacunas_coleta TO {p}",
    "GRANT SELECT ON v_saude_fontes TO {p}",
    "GRANT SELECT ON v_alarme_particao_default TO {p}",
    "GRANT EXECUTE ON FUNCTION clima_current_tenant() TO {p}",
    "GRANT EXECUTE ON FUNCTION clima_system_tenant() TO {p}",
    "GRANT EXECUTE ON FUNCTION clima_ensure_raw_partition(date) TO {p}",
]


def upgrade() -> None:
    # A view de alarme deixa de ser security_invoker: ela devolve apenas
    # contagem e min/max de timestamp da partição DEFAULT — nenhum dado de
    # tenant — e como referencia a partição diretamente, com security_invoker
    # exigiria GRANT em cada partição. Executada com os direitos do dono,
    # basta o GRANT na própria view.
    op.execute("DROP VIEW IF EXISTS v_alarme_particao_default")
    op.execute(
        """
        CREATE VIEW v_alarme_particao_default AS
        SELECT count(*) AS linhas, min(fetched_at) AS mais_antiga, max(fetched_at) AS mais_nova
        FROM raw_payloads_default
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
            RAISE WARNING 'papel {PAPEL} não existe; privilégios não aplicados. '
              'A aplicação NÃO deve conectar como superusuário — RLS seria ignorada.';
            RETURN;
          END IF;
          {"".join(f"EXECUTE '{g.format(p=PAPEL)}';" for g in GRANTS)}
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PAPEL}') THEN
            EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PAPEL}';
            EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {PAPEL}';
            EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {PAPEL}';
            EXECUTE 'REVOKE USAGE ON SCHEMA public FROM {PAPEL}';
          END IF;
        END $$
        """
    )
    op.execute("DROP VIEW IF EXISTS v_alarme_particao_default")
    op.execute(
        """
        CREATE VIEW v_alarme_particao_default WITH (security_invoker = true) AS
        SELECT count(*) AS linhas, min(fetched_at) AS mais_antiga, max(fetched_at) AS mais_nova
        FROM raw_payloads_default
        """
    )
