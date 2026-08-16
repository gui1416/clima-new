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

import hashlib
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from clima.config import TENANT_SISTEMA, config

API_DIR = Path(__file__).resolve().parents[2]

# Tabelas que cada teste começa vazias. Numa única instrução, porque source_records
# e parse_runs referenciam raw_payloads — truncar só o pai falharia por FK.
MUTAVEIS = (
    "event_field_claims, canonical_event_membros, canonical_event_snapshots, "
    "canonical_events, record_links, source_records, parse_runs, raw_payloads, "
    "payload_bodies, ingest_runs"
)


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


@pytest.fixture
def semear(dono: AsyncEngine):  # noqa: ANN201
    """Grava um payload bruto como a coleta faria, sem passar pela rede.

    Fica no conftest, e não num módulo de teste, porque `tests/` não é pacote —
    importar entre arquivos de teste quebraria a coleta dentro do contêiner.
    """

    async def _semear(corpo: bytes, quando: datetime | None = None, fonte: str = "usgs") -> int:
        instante = quando or datetime.now(UTC)
        sha = hashlib.sha256(corpo).digest()
        async with dono.begin() as c:
            run_id = (
                await c.execute(
                    text(
                        "INSERT INTO ingest_runs (tenant_id, source_id, resultado, finished_at) "
                        "VALUES (:t, :f, 'ok', now()) RETURNING id"
                    ),
                    {"t": TENANT_SISTEMA, "f": fonte},
                )
            ).scalar_one()
            await c.execute(
                text(
                    "INSERT INTO payload_bodies (sha256, body, bytes_total) "
                    "VALUES (:s, :b, :n) ON CONFLICT DO NOTHING"
                ),
                {"s": sha, "b": corpo, "n": len(corpo)},
            )
            return (
                await c.execute(
                    text(
                        """
                        INSERT INTO raw_payloads
                          (fetched_at, tenant_id, source_id, ingest_run_id, url,
                           http_status, body_sha256)
                        VALUES (:q, :t, :f, :r, 'https://exemplo.test/f', 200, :s)
                        RETURNING id
                        """
                    ),
                    {"q": instante, "t": TENANT_SISTEMA, "f": fonte, "r": run_id, "s": sha},
                )
            ).scalar_one()

    return _semear


async def _criar_tenant(eng: AsyncEngine, nome: str) -> uuid.UUID:
    async with eng.begin() as c:
        return (
            await c.execute(
                text("INSERT INTO tenants (nome) VALUES (:n) RETURNING id"), {"n": nome}
            )
        ).scalar_one()
