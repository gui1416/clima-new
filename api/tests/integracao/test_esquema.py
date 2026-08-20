"""O esquema realmente aplica e as partições realmente roteiam.

A migration 001 é SQL escrito à mão: particionamento, RLS, funções plpgsql e uma
partição DEFAULT. Nada disso é verificável sem um Postgres de verdade.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.config import TENANT_SISTEMA
from clima.db import sessao
from clima.ingest.particoes import garantir_particoes, linhas_na_default


async def _inserir_coleta(quando: datetime) -> str:
    """Insere uma coleta em ``fetched_at`` dado e devolve a partição que a recebeu."""
    corpo = f"corpo-{quando.isoformat()}".encode()
    sha = hashlib.sha256(corpo).digest()
    async with sessao() as s:
        run_id = (
            await s.execute(
                text(
                    "INSERT INTO ingest_runs (tenant_id, source_id) "
                    "VALUES (:t, 'usgs') RETURNING id"
                ),
                {"t": TENANT_SISTEMA},
            )
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO payload_bodies (sha256, body, bytes_total) "
                "VALUES (:s, :b, :n) ON CONFLICT DO NOTHING"
            ),
            {"s": sha, "b": corpo, "n": len(corpo)},
        )
        return (
            await s.execute(
                text(
                    """
                    INSERT INTO raw_payloads
                      (fetched_at, tenant_id, source_id, ingest_run_id, url,
                       http_status, body_sha256)
                    VALUES (:f, :t, 'usgs', :r, 'https://exemplo.test/f', 200, :s)
                    RETURNING tableoid::regclass::text
                    """
                ),
                {"f": quando, "t": TENANT_SISTEMA, "r": run_id, "s": sha},
            )
        ).scalar_one()


async def test_objetos_do_esquema_existem(dono: AsyncEngine) -> None:
    async with dono.connect() as c:
        tabelas = set(
            (
                await c.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
                    )
                )
            ).scalars()
        )
        views = set(
            (
                await c.execute(
                    text("SELECT viewname FROM pg_views WHERE schemaname = current_schema()")
                )
            ).scalars()
        )
        relkind = (
            await c.execute(text("SELECT relkind FROM pg_class WHERE relname = 'raw_payloads'"))
        ).scalar_one()

    assert {"tenants", "sources", "ingest_runs", "payload_bodies"} <= tabelas
    assert "raw_payloads_default" in tabelas
    assert {"v_lacunas_coleta", "v_saude_fontes", "v_alarme_particao_default"} <= views
    assert relkind == "p", "raw_payloads deveria ser tabela particionada"


async def test_fontes_bloqueadas_nascem_internas(dono: AsyncEngine) -> None:
    """Portão G4: Copernicus e INMET não podem redistribuir sem resposta jurídica."""
    async with dono.connect() as c:
        linhas = dict(
            (
                await c.execute(
                    text(
                        "SELECT id, redistribuicao FROM sources "
                        "WHERE id IN ('copernicus_ems','inmet','usgs')"
                    )
                )
            ).all()
        )
    assert linhas["copernicus_ems"] == "interna"
    assert linhas["inmet"] == "interna"
    assert linhas["usgs"] == "livre"


async def test_fontes_ativas_tem_conector_e_parser(dono: AsyncEngine) -> None:
    """Só fontes implementadas podem nascer ativas após as migrations."""
    async with dono.connect() as c:
        ativas = set(
            (await c.execute(text("SELECT id FROM sources WHERE ativa"))).scalars()
        )
    assert ativas == {"usgs", "emsc", "gdacs"}


async def test_coleta_do_mes_vai_para_a_particao_do_mes() -> None:
    agora = datetime.now(UTC)
    particao = await _inserir_coleta(agora)
    assert particao == f"raw_payloads_{agora:%Y_%m}"
    assert await linhas_na_default() == 0


async def test_particao_default_captura_mes_sem_particao() -> None:
    """A rede de segurança: sem ela, mês virado sem partição perderia a coleta."""
    distante = datetime.now(UTC) + timedelta(days=365 * 5)
    particao = await _inserir_coleta(distante)
    assert particao == "raw_payloads_default"
    assert await linhas_na_default() == 1


async def test_garantir_particoes_e_idempotente() -> None:
    primeira = await garantir_particoes()
    segunda = await garantir_particoes()
    assert primeira == segunda
    assert len(primeira) >= 3  # mês corrente + PARTICOES_FUTURAS


async def test_corpo_repetido_nao_duplica(dono: AsyncEngine) -> None:
    """A correção do esquema: corpo idêntico ocupa uma linha, a coleta ocupa duas.

    O esboço original do plano guardava o corpo dentro de raw_payloads com um
    índice único que incluía a chave de partição — nunca deduplicaria nada.
    """
    agora = datetime.now(UTC)
    await _inserir_coleta(agora)
    await _inserir_coleta(agora)  # mesmo fetched_at ⇒ mesmo corpo ⇒ mesmo sha

    async with dono.connect() as c:
        corpos = (await c.execute(text("SELECT count(*) FROM payload_bodies"))).scalar_one()
        coletas = (await c.execute(text("SELECT count(*) FROM raw_payloads"))).scalar_one()

    assert corpos == 1
    assert coletas == 2
