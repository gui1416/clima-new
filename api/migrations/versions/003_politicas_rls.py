"""politicas: UPDATE em ingest_runs, e tenant obrigatório para ler

Revision ID: 003_politicas_rls
Revises: 002_privilegios_app
Create Date: 2026-08-16

Duas falhas encontradas pela primeira execução da suíte de integração. Nenhuma
das duas dava erro — as duas produziam dado errado em silêncio, que é a razão de
a suíte existir.

── 1. Faltava política de UPDATE em ingest_runs ──────────────────────────────

A 001 criou políticas apenas ``FOR SELECT`` e ``FOR INSERT``. Com RLS ativa e
forçada, um UPDATE sem política encontra zero linhas elegíveis: a instrução
executa, não levanta exceção e não altera nada.

O ``ingest_run`` é aberto antes do fetch e fechado depois — e o fechamento é
justamente um UPDATE. Ou seja, **nenhum run jamais era fechado**: ``resultado``,
``finished_at``, ``etag`` e ``body_sha256`` ficavam NULL para sempre.

A cascata disso é maior que parece, porque três coisas filtram por
``resultado``:

* ``v_saude_fontes`` calcula ``ultima_coleta_ok`` com ``FILTER (WHERE resultado
  IN ('ok','nao_modificado'))`` → sempre NULL → toda fonte apareceria silenciosa
  → ``/saude`` responderia 503 permanentemente.
* ``v_lacunas_coleta`` só considera runs com resultado → nenhuma lacuna seria
  detectável, e a verificação de continuidade do portão G1 mediria nada.
* ``_ultimos_validadores`` busca a última coleta com ``resultado = 'ok'`` → sempre
  vazio → requisição condicional nunca funcionaria, e o USGS receberia um GET
  completo a cada 60 s.

O dado bruto era gravado corretamente; só a contabilidade sobre ele estava
quebrada. É o pior formato de defeito: o ativo parece íntegro e a instrumentação
que deveria provar isso mente.

── 2. Sessão sem tenant via linhas do tenant de sistema ─────────────────────

A política de leitura era ``tenant_id = clima_current_tenant() OR tenant_id =
clima_system_tenant()``. Com o GUC ausente, ``clima_current_tenant()`` devolve
NULL e a primeira comparação é NULL — mas a segunda continua verdadeira para as
linhas do pipeline compartilhado. Resultado: uma sessão sem tenant nenhum lia o
que o tenant de sistema possui.

Isso contradizia o "fail-closed" documentado. Sessão sem tenant é erro de
programação, e a resposta certa é não devolver linha alguma — não devolver um
subconjunto. Agora a política exige tenant definido antes de qualquer coisa.
"""

from __future__ import annotations

from alembic import op

revision = "003_politicas_rls"
down_revision = "002_privilegios_app"
branch_labels = None
depends_on = None

TABELAS = ("ingest_runs", "raw_payloads")


def upgrade() -> None:
    for tabela in TABELAS:
        # Leitura: exige tenant definido. Sem ele, nada — nem o de sistema.
        op.execute(f"DROP POLICY {tabela}_leitura ON {tabela}")
        op.execute(
            f"""
            CREATE POLICY {tabela}_leitura ON {tabela} FOR SELECT
            USING (
              clima_current_tenant() IS NOT NULL
              AND (tenant_id = clima_current_tenant()
                   OR tenant_id = clima_system_tenant())
            )
            """
        )

    # UPDATE só em ingest_runs, e só nas próprias linhas. raw_payloads e
    # payload_bodies continuam deliberadamente sem política de UPDATE e sem o
    # privilégio: lá a ausência é a garantia de imutabilidade, aqui era um furo.
    op.execute(
        """
        CREATE POLICY ingest_runs_atualizacao ON ingest_runs FOR UPDATE
        USING (tenant_id = clima_current_tenant())
        WITH CHECK (tenant_id = clima_current_tenant())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ingest_runs_atualizacao ON ingest_runs")
    for tabela in TABELAS:
        op.execute(f"DROP POLICY {tabela}_leitura ON {tabela}")
        op.execute(
            f"""
            CREATE POLICY {tabela}_leitura ON {tabela} FOR SELECT
            USING (tenant_id = clima_current_tenant()
                   OR tenant_id = clima_system_tenant())
            """
        )
