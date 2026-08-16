"""Isolamento entre tenants. É o teste que impede o pior tipo de falha silenciosa.

RLS mal configurada não dá erro — ela simplesmente devolve dados que não deveria.
Nenhum sintoma, nenhum log. Daí estes testes existirem antes de haver cliente.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.config import TENANT_SISTEMA
from clima.db import sessao, sessionmaker


async def _inserir_run(eng: AsyncEngine, tenant_id: uuid.UUID) -> int:
    """Insere um run com direitos de dono, para montar cenário."""
    async with eng.begin() as c:
        return (
            await c.execute(
                text(
                    "INSERT INTO ingest_runs (tenant_id, source_id) "
                    "VALUES (:t, 'usgs') RETURNING id"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()


async def test_papel_app_nao_ignora_rls() -> None:
    """O teste mais importante do arquivo.

    Superusuário e BYPASSRLS ignoram row-level security por completo, e FORCE ROW
    LEVEL SECURITY só sujeita o dono da tabela. Se a aplicação conectar como
    superusuário — o que a imagem oficial do Postgres cria por padrão — toda a RLS
    do projeto vira decoração e nada acusa.
    """
    async with sessionmaker()() as s:
        papel = (await s.execute(text("SELECT current_user"))).scalar_one()
        super_, bypass = (
            await s.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()

    assert super_ is False, f"a aplicação conecta como {papel!r}, que é SUPERUSER — RLS é inócua"
    assert bypass is False, f"{papel!r} tem BYPASSRLS — RLS é inócua"


async def test_sem_tenant_nao_ve_nada(dono: AsyncEngine, tenant_a: uuid.UUID) -> None:
    """Fail-closed: sessão sem GUC de tenant vê zero linhas, não o banco inteiro."""
    await _inserir_run(dono, tenant_a)
    await _inserir_run(dono, TENANT_SISTEMA)

    async with sessionmaker()() as s:  # sem passar por clima.db.sessao()
        n = (await s.execute(text("SELECT count(*) FROM ingest_runs"))).scalar_one()

    assert n == 0


async def test_tenant_ve_o_proprio_e_o_de_sistema(
    dono: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _inserir_run(dono, tenant_a)
    await _inserir_run(dono, tenant_b)
    await _inserir_run(dono, TENANT_SISTEMA)

    async with sessao(tenant_a) as s:
        visiveis = set(
            (await s.execute(text("SELECT DISTINCT tenant_id FROM ingest_runs"))).scalars()
        )

    # O pipeline de ingestão é compartilhado: o tenant lê as linhas de sistema.
    assert visiveis == {tenant_a, TENANT_SISTEMA}
    assert tenant_b not in visiveis


async def test_nao_escreve_no_tenant_alheio(tenant_a: uuid.UUID, tenant_b: uuid.UUID) -> None:
    """Ler o de sistema é permitido; escrever fora do próprio tenant, não."""
    with pytest.raises(DBAPIError):
        async with sessao(tenant_a) as s:
            await s.execute(
                text("INSERT INTO ingest_runs (tenant_id, source_id) VALUES (:t, 'usgs')"),
                {"t": tenant_b},
            )


async def test_app_nao_apaga_payload_raw(dono: AsyncEngine) -> None:
    """Imutabilidade do ativo histórico como privilégio negado, não como disciplina."""
    for tabela in ("raw_payloads", "payload_bodies"):
        with pytest.raises(DBAPIError):
            async with sessao() as s:
                await s.execute(text(f"DELETE FROM {tabela}"))
