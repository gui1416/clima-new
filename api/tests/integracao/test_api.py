"""A API de produto, contra banco real e via ASGI (sem subir servidor).

O teste que mais importa aqui é o da trava de licença: fonte com
``redistribuicao = 'interna'`` participa da contagem e não entrega conteúdo. É o
portão G4 do plano verificado por código em vez de por lembrança.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from clima.app import app
from clima.config import TENANT_SISTEMA
from clima.correlation import correlacionar
from clima.ingest.parser import analisar_pendentes

FIXTURE = Path(__file__).parents[1] / "fixtures" / "usgs-all-hour.json"


@pytest.fixture
async def cliente():  # noqa: ANN201
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as c:
        yield c


@pytest.fixture
async def com_dados(semear) -> None:  # noqa: ANN001
    await semear(FIXTURE.read_bytes())
    await analisar_pendentes()
    # A API lê v_eventos_canonicos, então o motor precisa ter rodado.
    await correlacionar(horas=24 * 365 * 10)


async def test_lista_eventos(cliente: httpx.AsyncClient, com_dados: None) -> None:
    # A fixture tem 11 sismos, só 3 com M >= 2,5 — o piso de apresentação.
    r = await cliente.get("/api/eventos", params={"horas": 24 * 30})
    assert r.status_code == 200
    corpo = r.json()

    assert corpo["total"] == 3
    assert len(corpo["itens"]) == 3
    # A honestidade sobre o estado do produto viaja em toda resposta de lista.
    assert corpo["deduplicado"] is True, "os itens são eventos canônicos"
    assert "fonte" in corpo["aviso"]

    e = corpo["itens"][0]
    assert e["fontes_confirmando"] >= 1
    assert e["confianca"] > 0, "confiança vem do motor e nunca aparece sem a contagem"
    assert e["metrica_rotulo"] == "magnitude"
    assert e["magnitude"] is not None
    assert e["severidade"] in {"critical", "high", "moderate"}
    assert e["titulo"].startswith("Sismo M ")
    assert "," in e["titulo"], "número em pt-BR usa vírgula decimal"


async def test_piso_de_magnitude_e_de_apresentacao(
    cliente: httpx.AsyncClient, com_dados: None, dono: AsyncEngine
) -> None:
    """Baixar o piso revela o que já estava gravado: nada é filtrado na ingestão."""
    baixo = (await cliente.get("/api/eventos", params={"horas": 24 * 30, "magnitude_minima": 0})).json()
    assert baixo["total"] == 11

    async with dono.connect() as c:
        gravados = (await c.execute(text("SELECT count(*) FROM v_registros_atuais"))).scalar_one()
    assert gravados == 11, "o banco guarda tudo; o corte é só na resposta"


async def test_filtro_por_bbox(cliente: httpx.AsyncClient, com_dados: None) -> None:
    # A fixture é dominada por sismos da Califórnia.
    dentro = (
        await cliente.get(
            "/api/eventos",
            params={"horas": 24 * 30, "magnitude_minima": 0, "bbox": "-125,32,-114,42"},
        )
    ).json()
    fora = (
        await cliente.get(
            "/api/eventos", params={"horas": 24 * 30, "magnitude_minima": 0, "bbox": "100,-40,140,-10"}
        )
    ).json()

    assert dentro["total"] > 0
    assert fora["total"] == 0
    assert dentro["total"] < 11 or fora["total"] == 0


async def test_bbox_malformada_da_422(cliente: httpx.AsyncClient) -> None:
    assert (await cliente.get("/api/eventos", params={"bbox": "1,2,3"})).status_code == 422
    assert (await cliente.get("/api/eventos", params={"bbox": "a,b,c,d"})).status_code == 422


async def test_detalhe_com_procedencia(cliente: httpx.AsyncClient, com_dados: None) -> None:
    lista = (await cliente.get("/api/eventos", params={"horas": 24 * 30})).json()
    ident = lista["itens"][0]["id"]
    assert len(ident) == 36, "id do evento canônico é uuid"

    r = await cliente.get(f"/api/eventos/{ident}")
    assert r.status_code == 200
    d = r.json()

    assert len(d["procedencia"]) == 1
    p = d["procedencia"][0]
    assert p["fonte"] == "usgs"
    assert p["conteudo_restrito"] is False

    # O painel de procedência: campo por campo, o que cada fonte afirma.
    campos = {c["campo"]: c for c in d["campos"]}
    assert "magnitude" in campos
    assert campos["magnitude"]["valores"][0]["vencedor"] is True
    assert campos["magnitude"]["valores"][0]["valor"] == d["magnitude"]
    # Com uma fonte não há divergência possível.
    assert campos["magnitude"]["divergente"] is False


async def test_evento_inexistente_da_404(cliente: httpx.AsyncClient) -> None:
    assert (
        await cliente.get("/api/eventos/00000000-0000-0000-0000-000000000099")
    ).status_code == 404


async def test_estatisticas(cliente: httpx.AsyncClient, com_dados: None) -> None:
    e = (
        await cliente.get("/api/estatisticas", params={"horas": 24 * 30, "magnitude_minima": 0})
    ).json()
    assert e["eventos_total"] == 11
    assert sum(e["por_severidade"].values()) == 11
    assert sum(e["por_status"].values()) == 11
    assert e["magnitude_maxima"] == 2.78
    assert e["fontes_ativas"] == 2, "USGS e EMSC"
    assert e["deduplicado"] is True
    assert e["eventos_multifonte"] == 0, "uma fonte na fixture"


async def test_fonte_interna_nao_vaza_conteudo(
    cliente: httpx.AsyncClient, dono: AsyncEngine, semear
) -> None:  # noqa: ANN001
    """Portão G4: fonte restrita entra na contagem e na confiança, não na resposta.

    Sem este teste a trava de licença depende de alguém lembrar dela ao escrever o
    próximo endpoint. Agora ela precisa valer também nas afirmações por campo, que
    são o caminho novo pelo qual conteúdo de fonte poderia escapar.
    """
    raw_id = await semear(FIXTURE.read_bytes())
    async with dono.begin() as c:
        fetched = (
            await c.execute(text("SELECT fetched_at FROM raw_payloads WHERE id = :i"), {"i": raw_id})
        ).scalar_one()
        await c.execute(
            text(
                """
                INSERT INTO source_records
                  (tenant_id, source_id, source_event_id, raw_payload_id, raw_fetched_at,
                   observed_at, source_updated_at, event_type, geom, lugar, magnitude,
                   profundidade_km, metrics, xrefs, status)
                VALUES (:t, 'inmet', 'alerta-1', :r, :f, now(), now(), 'earthquake',
                        'SRID=4326;POINT(-47.9 -15.8)', 'Brasília', 5.5, 10,
                        '{"segredo": 1}'::jsonb, '{"inmet": "alerta-1"}'::jsonb, 'reviewed')
                """
            ),
            {"t": TENANT_SISTEMA, "r": raw_id, "f": fetched},
        )

    await correlacionar(horas=24)

    async with dono.connect() as c:
        ident = (
            await c.execute(
                text(
                    """
                    SELECT e.id FROM canonical_events e
                    JOIN canonical_event_membros m ON m.canonical_event_id = e.id
                    WHERE m.source_id = 'inmet'
                    """
                )
            )
        ).scalar_one()

    d = (await cliente.get(f"/api/eventos/{ident}")).json()

    p = d["procedencia"][0]
    assert p["fonte"] == "inmet"
    assert p["conteudo_restrito"] is True, "a existência da fonte sai; o conteúdo não"

    # O caminho novo: nenhuma afirmação de fonte restrita pode trazer valor.
    for campo in d["campos"]:
        for v in campo["valores"]:
            if v["fonte"] == "inmet":
                assert v["valor"] is None, f"conteúdo de fonte interna vazou em {campo['campo']}"
                assert v["conteudo_restrito"] is True

    assert d["metricas"] == {}, "métricas de fonte interna não podem sair"
    # Mas o evento existe e conta como confirmado.
    assert d["fontes_confirmando"] == 1
    assert d["confianca"] > 0
