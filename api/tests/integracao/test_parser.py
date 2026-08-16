"""Parser contra banco real: idempotência, revisão append-only e replay."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.ingest.parser import analisar_pendentes, pendencia, reprocessar

FIXTURE = Path(__file__).parents[1] / "fixtures" / "usgs-all-hour.json"


async def _contar(dono: AsyncEngine) -> tuple[int, int]:
    async with dono.connect() as c:
        return (
            (await c.execute(text("SELECT count(*) FROM source_records"))).scalar_one(),
            (await c.execute(text("SELECT count(*) FROM v_registros_atuais"))).scalar_one(),
        )


async def test_analisa_payload_real(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    await semear(FIXTURE.read_bytes())
    assert await pendencia() == 1

    r = await analisar_pendentes()
    assert r == {"payloads": 1, "novos": 11, "vistos": 11, "erros": 0}
    assert await pendencia() == 0
    assert await _contar(dono) == (11, 11)

    async with dono.connect() as c:
        lat, lon, mag, sev = (
            await c.execute(
                text(
                    """
                    SELECT ST_Y(geom::geometry), ST_X(geom::geometry), magnitude, severidade
                    FROM v_registros_atuais ORDER BY magnitude DESC LIMIT 1
                    """
                )
            )
        ).one()
    assert -90 <= lat <= 90 and -180 <= lon <= 180
    assert mag == 2.78  # maior magnitude da fixture
    assert sev == "moderate"  # M 2,78 não é 'high'


async def test_reanalisar_o_mesmo_payload_nao_duplica(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """O mesmo evento reaparece em ~60 coletas seguidas. Sem isto, o banco infla."""
    corpo = FIXTURE.read_bytes()
    await semear(corpo, datetime.now(UTC) - timedelta(minutes=2))
    await analisar_pendentes()
    await semear(corpo, datetime.now(UTC) - timedelta(minutes=1))
    r = await analisar_pendentes()

    assert r["payloads"] == 1
    assert r["novos"] == 0, "mesma revisão não deve gerar linha nova"
    assert r["vistos"] == 11
    assert await _contar(dono) == (11, 11)


async def test_revisao_da_fonte_vira_linha_nova(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """Magnitude revisada = novo snapshot, nunca UPDATE (princípio 2)."""
    doc = json.loads(FIXTURE.read_bytes())
    await semear(json.dumps(doc).encode(), datetime.now(UTC) - timedelta(minutes=2))
    await analisar_pendentes()

    alvo = doc["features"][0]
    id_alvo = alvo["id"]
    mag_antiga = alvo["properties"]["mag"]
    alvo["properties"]["mag"] = mag_antiga + 0.4
    alvo["properties"]["updated"] += 60_000
    alvo["properties"]["status"] = "reviewed"
    await semear(json.dumps(doc).encode(), datetime.now(UTC) - timedelta(minutes=1))

    r = await analisar_pendentes()
    assert r["novos"] == 1

    total, atuais = await _contar(dono)
    assert total == 12, "a revisão soma linha, não substitui"
    assert atuais == 11, "o estado atual continua com um registro por evento"

    async with dono.connect() as c:
        mag, status, revisoes = (
            await c.execute(
                text(
                    "SELECT magnitude, status, revisoes FROM v_registros_atuais "
                    "WHERE source_event_id = :i"
                ),
                {"i": id_alvo},
            )
        ).one()
    assert mag == mag_antiga + 0.4, "a view precisa mostrar a revisão mais recente"
    assert status == "reviewed"
    assert revisoes == 2

    # E a versão antiga continua no histórico.
    async with dono.connect() as c:
        historico = sorted(
            (
                await c.execute(
                    text("SELECT magnitude FROM source_records WHERE source_event_id = :i"),
                    {"i": id_alvo},
                )
            ).scalars()
        )
    assert historico == sorted([mag_antiga, mag_antiga + 0.4])


async def test_replay_reconstroi_a_partir_do_bruto(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """A operação que justifica guardar payload_raw."""
    await semear(FIXTURE.read_bytes())
    await analisar_pendentes()
    antes, _ = await _contar(dono)

    assert await reprocessar("usgs") == 1
    assert await pendencia() == 1, "apagar parse_runs devolve o payload para a fila"

    r = await analisar_pendentes()
    assert r["payloads"] == 1
    # Os registros já existem, então nada de novo entra — e nada se perde.
    assert r["novos"] == 0
    assert (await _contar(dono))[0] == antes


async def test_payload_ilegivel_registra_erro_e_nao_trava_a_fila(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    await semear(b"nao e json", datetime.now(UTC) - timedelta(minutes=2))
    await semear(FIXTURE.read_bytes(), datetime.now(UTC) - timedelta(minutes=1))

    r = await analisar_pendentes()
    assert r["erros"] == 1
    assert r["novos"] == 11, "o payload bom precisa ser analisado apesar do ruim"

    async with dono.connect() as c:
        erro = (
            await c.execute(text("SELECT erro FROM parse_runs WHERE erro IS NOT NULL"))
        ).scalar_one()
    assert "JSONDecodeError" in erro or "Expecting value" in erro
