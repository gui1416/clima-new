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


async def test_lista_eventos(cliente: httpx.AsyncClient, com_dados: None) -> None:
    # A fixture tem 11 sismos, só 3 com M >= 2,5 — o piso de apresentação.
    r = await cliente.get("/api/eventos", params={"horas": 24 * 30})
    assert r.status_code == 200
    corpo = r.json()

    assert corpo["total"] == 3
    assert len(corpo["itens"]) == 3
    # A honestidade sobre o estado do produto viaja em toda resposta de lista.
    assert corpo["deduplicado"] is False
    assert "Fase 2" in corpo["aviso"]

    e = corpo["itens"][0]
    assert e["fontes_confirmando"] == 1, "sem motor de correlação, é 1 e a API não finge"
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
    assert ident.startswith("usgs:")

    r = await cliente.get(f"/api/eventos/{ident}")
    assert r.status_code == 200
    d = r.json()

    assert len(d["procedencia"]) == 1, "uma fonte hoje — a lista já tem a forma final"
    p = d["procedencia"][0]
    assert p["fonte"] == "usgs"
    assert p["conteudo_restrito"] is False
    assert p["magnitude"] == d["magnitude"]
    assert p["revisoes"] >= 1
    # O xref é o que a Fase 2 vai usar para ligar fontes de forma determinística.
    assert d["xrefs"]["usgs"] == ident.split(":", 1)[1]


async def test_evento_inexistente_da_404(cliente: httpx.AsyncClient) -> None:
    assert (await cliente.get("/api/eventos/usgs:nao-existe")).status_code == 404


async def test_estatisticas(cliente: httpx.AsyncClient, com_dados: None) -> None:
    e = (
        await cliente.get("/api/estatisticas", params={"horas": 24 * 30, "magnitude_minima": 0})
    ).json()
    assert e["eventos_total"] == 11
    assert sum(e["por_severidade"].values()) == 11
    assert sum(e["por_status"].values()) == 11
    assert e["magnitude_maxima"] == 2.78
    assert e["fontes_ativas"] == 1
    assert e["deduplicado"] is False


async def test_fonte_interna_nao_vaza_conteudo(
    cliente: httpx.AsyncClient, dono: AsyncEngine, semear
) -> None:  # noqa: ANN001
    """Portão G4: Copernicus e INMET entram na contagem, não na resposta.

    Sem este teste, a trava de licença depende de alguém lembrar dela ao escrever
    o próximo endpoint.
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

    d = (await cliente.get("/api/eventos/inmet:alerta-1")).json()
    p = d["procedencia"][0]

    assert p["conteudo_restrito"] is True
    assert p["magnitude"] is None, "magnitude de fonte 'interna' não pode sair"
    assert p["lugar"] is None
    assert p["profundidade_km"] is None
    assert d["metricas"] == {}, "métricas de fonte 'interna' não podem sair"
    # A existência do registro e o xref continuam disponíveis: é o que permite
    # usar a fonte para correlação e confiança sem redistribuir o dado.
    assert d["xrefs"] == {"inmet": "alerta-1"}
    assert p["fonte"] == "inmet"
