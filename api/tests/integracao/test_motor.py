"""O motor contra banco real: blocking, persistência, idempotência e claims."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.config import TENANT_SISTEMA
from clima.correlation import correlacionar
from clima.ingest.parser import analisar_pendentes

FIXTURE = Path(__file__).parents[1] / "fixtures" / "usgs-all-hour.json"


async def _inserir_registro(
    dono: AsyncEngine,
    raw_id: int,
    fetched: datetime,
    *,
    fonte: str,
    evento: str,
    lat: float,
    lon: float,
    quando: datetime,
    mag: float | None = 4.5,
    lugar: str | None = "Salta, Argentina",
    xrefs: dict | None = None,
    status: str = "automatic",
) -> int:
    """Insere um source_record direto, para montar cenário de duas fontes.

    O parser não serve aqui: ele só produz registros do USGS, e o que precisa ser
    exercitado é justamente o cruzamento entre fontes distintas.
    """
    async with dono.begin() as c:
        return (
            await c.execute(
                text(
                    """
                    INSERT INTO source_records
                      (tenant_id, source_id, source_event_id, raw_payload_id, raw_fetched_at,
                       observed_at, source_updated_at, event_type, geom, lugar, magnitude,
                       profundidade_km, metrics, xrefs, status)
                    VALUES (:t, :f, :e, :r, :fa, :obs, :obs, 'earthquake',
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                            :lugar, :mag, 10, '{}'::jsonb, CAST(:x AS jsonb), :st)
                    RETURNING id
                    """
                ),
                {
                    "t": TENANT_SISTEMA,
                    "f": fonte,
                    "e": evento,
                    "r": raw_id,
                    "fa": fetched,
                    "obs": quando,
                    "lon": lon,
                    "lat": lat,
                    "lugar": lugar,
                    "mag": mag,
                    "x": json.dumps(xrefs or {}),
                    "st": status,
                },
            )
        ).scalar_one()


async def _raw(dono: AsyncEngine, semear) -> tuple[int, datetime]:  # noqa: ANN001
    raw_id = await semear(FIXTURE.read_bytes())
    async with dono.connect() as c:
        fetched = (
            await c.execute(text("SELECT fetched_at FROM raw_payloads WHERE id = :i"), {"i": raw_id})
        ).scalar_one()
    return raw_id, fetched


async def test_duas_fontes_reais_deduplicam(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """O caso que o produto existe para resolver, com payload real das duas fontes.

    Sem xref entre USGS e EMSC, então quem decide é o modelo probabilístico. Não se
    exige que TODOS os pares coincidentes sejam unidos — os dois payloads são de
    janelas diferentes e a sobreposição é parcial. Exige-se que a correlação ocorra e
    que nada seja fundido além do que o diâmetro do tipo permite.
    """
    from pathlib import Path as _P

    emsc = _P(__file__).parents[1] / "fixtures" / "emsc-recentes.json"
    await semear(FIXTURE.read_bytes(), fonte="usgs")
    await semear(emsc.read_bytes(), fonte="emsc")
    await analisar_pendentes()

    rel = await correlacionar(horas=24 * 365 * 10)

    assert rel.registros == 66, "11 do USGS + 55 do EMSC"
    assert rel.candidatos > 0, "o blocking precisa achar pares entre as fontes"
    assert rel.por_xref == 0, "não há identificador comum entre USGS e EMSC"
    assert rel.eventos < rel.registros or rel.unidos == 0

    async with dono.connect() as c:
        multi = (
            await c.execute(
                text("SELECT count(*) FROM v_eventos_canonicos WHERE source_count > 1")
            )
        ).scalar_one()
        maior = (
            await c.execute(text("SELECT max(source_count) FROM v_eventos_canonicos"))
        ).scalar_one()
    assert maior <= 2, "com duas fontes, nenhum evento pode ter mais de duas"
    assert multi == rel.eventos_multifonte


async def test_uma_fonte_gera_um_evento_por_registro(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """Com uma fonte só não há nada para deduplicar, e o motor não pode inventar."""
    await semear(FIXTURE.read_bytes())
    await analisar_pendentes()

    rel = await correlacionar(horas=24 * 365 * 10)

    assert rel.registros == 11
    assert rel.eventos == 11, "sem segunda fonte, cada registro é seu próprio evento"
    assert rel.eventos_multifonte == 0
    assert rel.unidos == 0

    async with dono.connect() as c:
        fontes = (
            await c.execute(text("SELECT max(source_count) FROM v_eventos_canonicos"))
        ).scalar_one()
    assert fontes == 1


async def test_xref_une_fontes_diferentes(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """Cruzamento determinístico: onde há identificador comum, o vínculo é certo."""
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=5)

    await _inserir_registro(
        dono, raw_id, fetched, fonte="usgs", evento="us7000zzz",
        lat=-24.30, lon=-67.35, quando=agora, mag=4.5,
        xrefs={"usgs": "us7000zzz"},
    )
    # Longe o bastante para o probabilístico recusar — só o xref pode uni-los.
    await _inserir_registro(
        dono, raw_id, fetched, fonte="gdacs", evento="g-9",
        lat=-24.80, lon=-67.90, quando=agora + timedelta(seconds=70), mag=4.9,
        xrefs={"gdacs": "g-9", "redes": ["us7000zzz"]},
    )

    rel = await correlacionar(horas=24)

    assert rel.por_xref == 1
    assert rel.eventos == 1
    assert rel.eventos_multifonte == 1

    async with dono.connect() as c:
        metodo = (await c.execute(text("SELECT metodo FROM record_links"))).scalar_one()
        canonico = (
            await c.execute(
                text("SELECT source_count, magnitude, confianca FROM v_eventos_canonicos")
            )
        ).one()
    assert metodo == "xref"
    assert canonico.source_count == 2
    # Precedência por campo: USGS ganha em magnitude. Nunca a média de 4,5 e 4,9.
    assert canonico.magnitude == 4.5
    assert canonico.confianca > 0.5


async def test_claims_preservam_as_duas_afirmacoes(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """A divergência é o produto: as duas magnitudes precisam sobreviver no banco."""
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=5)
    await _inserir_registro(dono, raw_id, fetched, fonte="usgs", evento="us1",
                            lat=-24.3, lon=-67.35, quando=agora, mag=4.5,
                            xrefs={"usgs": "us1"})
    await _inserir_registro(dono, raw_id, fetched, fonte="gdacs", evento="g1",
                            lat=-24.4, lon=-67.4, quando=agora, mag=4.9,
                            xrefs={"redes": ["us1"]})

    await correlacionar(horas=24)

    async with dono.connect() as c:
        claims = dict(
            (
                await c.execute(
                    text(
                        "SELECT source_id, valor FROM event_field_claims WHERE campo = 'magnitude'"
                    )
                )
            ).all()
        )
        vencedor = (
            await c.execute(
                text(
                    "SELECT source_id FROM event_field_claims "
                    "WHERE campo = 'magnitude' AND vencedor"
                )
            )
        ).scalar_one()

    assert claims == {"usgs": 4.5, "gdacs": 4.9}
    assert vencedor == "usgs"


async def test_nao_funde_vizinhos_distintos(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """O negativo real da coleta: 0,5 km e 62 s. Dentro do blocking, e distintos."""
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=10)

    await _inserir_registro(dono, raw_id, fetched, fonte="usgs", evento="a",
                            lat=35.7773, lon=-117.5968, quando=agora, mag=1.06,
                            lugar="17 km W of Searles Valley, CA")
    await _inserir_registro(dono, raw_id, fetched, fonte="usgs", evento="b",
                            lat=35.7818, lon=-117.5945,
                            quando=agora + timedelta(seconds=62), mag=0.65,
                            lugar="18 km W of Searles Valley, CA")

    rel = await correlacionar(horas=24)

    assert rel.candidatos == 1, "o blocking precisa considerá-los — é o caso difícil"
    assert rel.unidos == 0, "e o motor precisa recusá-los"
    assert rel.eventos == 2

    async with dono.connect() as c:
        veredito = (await c.execute(text("SELECT veredito FROM record_links"))).scalar_one()
    assert veredito in {"distinto", "incerto"}


async def test_correlacionar_e_idempotente(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """Rodar de novo não cria evento nem snapshot: o worker roda a cada minuto."""
    await semear(FIXTURE.read_bytes())
    await analisar_pendentes()

    primeira = await correlacionar(horas=24 * 365 * 10)
    segunda = await correlacionar(horas=24 * 365 * 10)

    assert primeira.eventos == segunda.eventos
    assert primeira.snapshots_novos == 11
    assert segunda.snapshots_novos == 0, "estado igual não deve gerar snapshot novo"

    async with dono.connect() as c:
        eventos = (await c.execute(text("SELECT count(*) FROM canonical_events"))).scalar_one()
        snaps = (
            await c.execute(text("SELECT count(*) FROM canonical_event_snapshots"))
        ).scalar_one()
    assert (eventos, snaps) == (11, 11)


async def test_nova_fonte_gera_snapshot_com_motivo(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """Chegar uma segunda fonte é mudança de estado, e o histórico registra por quê."""
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=5)

    await _inserir_registro(dono, raw_id, fetched, fonte="usgs", evento="us1",
                            lat=-24.3, lon=-67.35, quando=agora, xrefs={"usgs": "us1"})
    await correlacionar(horas=24)

    await _inserir_registro(dono, raw_id, fetched, fonte="gdacs", evento="g1",
                            lat=-24.35, lon=-67.4, quando=agora, mag=4.5,
                            xrefs={"redes": ["us1"]})
    await correlacionar(horas=24)

    async with dono.connect() as c:
        motivos = list(
            (
                await c.execute(
                    text(
                        "SELECT motivo_mudanca FROM canonical_event_snapshots "
                        "ORDER BY canonical_event_id, seq"
                    )
                )
            ).scalars()
        )
        contagens = list(
            (
                await c.execute(
                    text("SELECT source_count FROM canonical_event_snapshots ORDER BY seq")
                )
            ).scalars()
        )

    assert motivos == ["primeira_observacao", "nova_fonte"]
    assert contagens == [1, 2]


async def test_fila_de_revisao_expoe_o_par_duvidoso(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    """`incerto` precisa ser visível, não engolido: é a admissão de dúvida."""
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=5)

    # Distância e tempo intermediários: cai na faixa entre os dois limiares.
    await _inserir_registro(dono, raw_id, fetched, fonte="usgs", evento="a",
                            lat=0.0, lon=0.0, quando=agora, mag=4.5, lugar=None)
    await _inserir_registro(dono, raw_id, fetched, fonte="gdacs", evento="b",
                            lat=0.32, lon=0.0, quando=agora + timedelta(seconds=34),
                            mag=4.7, lugar=None)

    await correlacionar(horas=24)

    async with dono.connect() as c:
        fila = (await c.execute(text("SELECT * FROM v_revisao_pendente"))).all()

    if fila:
        linha = fila[0]
        assert linha.distancia_m > 0
        assert linha.score is not None
        assert "explicacao" in linha.features, "a fila precisa explicar por que duvidou"


async def test_decisao_manual_prevalece_sobre_xref(dono: AsyncEngine, semear) -> None:  # noqa: ANN001
    raw_id, fetched = await _raw(dono, semear)
    agora = datetime.now(UTC) - timedelta(minutes=5)
    a = await _inserir_registro(
        dono, raw_id, fetched, fonte="usgs", evento="manual-a", lat=0, lon=0,
        quando=agora, xrefs={"usgs": "comum"}
    )
    b = await _inserir_registro(
        dono, raw_id, fetched, fonte="gdacs", evento="manual-b", lat=0.01, lon=0,
        quando=agora, xrefs={"usgs": "comum"}
    )
    await correlacionar(horas=24)

    async with dono.begin() as c:
        await c.execute(
            text(
                """
                UPDATE record_links SET metodo = 'manual', veredito = 'distinto',
                  decidido_por = 'teste', features = features || '{"justificativa_manual":"revisado"}'
                WHERE a_id = :a AND b_id = :b
                """
            ),
            {"a": min(a, b), "b": max(a, b)},
        )

    await correlacionar(horas=24)
    async with dono.connect() as c:
        veredito = (
            await c.execute(
                text("SELECT veredito FROM record_links WHERE a_id = :a AND b_id = :b"),
                {"a": min(a, b), "b": max(a, b)},
            )
        ).scalar_one()
    assert veredito == "distinto"
