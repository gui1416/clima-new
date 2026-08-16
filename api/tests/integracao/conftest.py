"""Fixtures da suíte de integração.

Vivem neste subdiretório e não em ``tests/`` porque a limpeza é ``autouse`` e
exige banco: se estivesse na raiz, os testes unitários — que rodam sem
infraestrutura nenhuma — passariam a depender de Postgres.

Roda contra o Postgres de ``compose.test.yaml``. Duas conexões, de propósito:

* **dono** (``DATABASE_URL_ADMIN``) — migrations e limpeza. É superusuário, então
  ignora RLS; serve para montar cenário, nunca para verificar comportamento.
* **aplicação** (``DATABASE_URL``, papel ``clima_app``) — é por onde os testes
  exercitam o código de produção. Sem BYPASSRLS, é o que faz os testes de
  isolamento medirem algo real.

A limpeza usa o dono porque ``clima_app`` deliberadamente não tem DELETE nem
TRUNCATE em ``raw_payloads``/``payload_bodies`` — a imutabilidade do ativo
histórico é privilégio negado, não só disciplina.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from clima.config import config

API_DIR = Path(__file__).resolve().parents[2]

# Tabelas que cada teste começa vazias. Uma única instrução resolve as FKs entre elas.
MUTAVEIS = "raw_payloads, payload_bodies, ingest_runs"


@pytest.fixture(scope="session")
def migrado() -> Iterator[None]:
    cfg = config()
    # Guarda contra rodar a suíte — que TRUNCA tabelas — contra um banco real.
    if "test" not in cfg.database_url_migracao:
        pytest.fail(
            "DATABASE_URL_ADMIN não aponta para um banco de teste. "
            "Use ./scripts/testar.sh; a suíte apaga dados."
        )
    r = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=API_DIR,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(f"alembic upgrade head falhou:\n{r.stdout}\n{r.stderr}")
    yield


@pytest.fixture
async def dono(migrado: None) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(config().database_url_migracao)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def limpar(dono: AsyncEngine) -> AsyncIterator[None]:
    async with dono.begin() as c:
        await c.execute(text(f"TRUNCATE {MUTAVEIS} RESTART IDENTITY"))
        await c.execute(text("DELETE FROM tenants WHERE id <> clima_system_tenant()"))
    yield


@pytest.fixture
async def tenant_a(dono: AsyncEngine) -> uuid.UUID:
    return await _criar_tenant(dono, "Tenant A")


@pytest.fixture
async def tenant_b(dono: AsyncEngine) -> uuid.UUID:
    return await _criar_tenant(dono, "Tenant B")


async def _criar_tenant(eng: AsyncEngine, nome: str) -> uuid.UUID:
    async with eng.begin() as c:
        return (
            await c.execute(
                text("INSERT INTO tenants (nome) VALUES (:n) RETURNING id"), {"n": nome}
            )
        ).scalar_one()
