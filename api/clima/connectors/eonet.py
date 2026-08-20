"""Conector NASA EONET para eventos naturais observados e abertos."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from clima.connectors.base import Observacao, Resposta, Validadores, resposta_de_httpx

FEED = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=500"

TIPOS = {
    "wildfires": "wildfire",
    "severeStorms": "storm",
    "volcanoes": "volcano",
    "floods": "flood",
    "landslides": "landslide",
    "seaLakeIce": "sea_ice",
    "drought": "drought",
    "dustHaze": "dust_haze",
    "snow": "snow",
    "tempExtremes": "temperature_extreme",
    "waterColor": "water_color",
    "manmade": "manmade",
}


def _instante(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _ponto(geometria: dict[str, Any]) -> tuple[float, float] | None:
    tipo = geometria.get("type")
    coordenadas = geometria.get("coordinates") or []
    if tipo == "Point" and len(coordenadas) >= 2:
        return float(coordenadas[1]), float(coordenadas[0])
    if tipo == "Polygon" and coordenadas and coordenadas[0]:
        pontos = coordenadas[0]
        return (
            sum(float(p[1]) for p in pontos) / len(pontos),
            sum(float(p[0]) for p in pontos) / len(pontos),
        )
    return None


def _id_da_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    ultimo = url.rstrip("/").rsplit("/", 1)[-1]
    return ultimo if re.fullmatch(r"[A-Za-z0-9_.:-]+", ultimo) else None


class ConectorEONET:
    id = "nasa_eonet"

    def __init__(self, url: str = FEED) -> None:
        self.url = url

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        resposta = await cliente.get(self.url, headers=anteriores.cabecalhos())
        return resposta_de_httpx(resposta)

    def analisar(self, corpo: bytes) -> Sequence[Observacao]:
        doc = json.loads(corpo)
        if not isinstance(doc.get("events"), list):
            raise ValueError("esperava objeto EONET com events[]")

        observacoes: list[Observacao] = []
        for evento in doc["events"]:
            evento_id = evento.get("id")
            geometrias = evento.get("geometry") or []
            categorias = evento.get("categories") or []
            if evento_id is None or not geometrias or not categorias:
                continue

            # O último item é o estado geográfico mais recente do evento.
            atual = max(geometrias, key=lambda g: str(g.get("date") or ""))
            ponto = _ponto(atual)
            ocorreu = _instante(atual.get("date"))
            if ponto is None or ocorreu is None:
                continue

            categoria = str(categorias[0].get("id") or "natural_event")
            fontes = evento.get("sources") or []
            ids_origem = [i for fonte in fontes if (i := _id_da_url(fonte.get("url")))]
            metrics: dict[str, object] = {"categoria_eonet": categoria}
            if atual.get("magnitudeValue") is not None:
                metrics["magnitude_valor"] = atual["magnitudeValue"]
            if atual.get("magnitudeUnit"):
                metrics["magnitude_unidade"] = atual["magnitudeUnit"]

            observacoes.append(
                Observacao(
                    source_event_id=str(evento_id),
                    observed_at=ocorreu,
                    source_updated_at=ocorreu,
                    event_type=TIPOS.get(categoria, categoria),
                    lat=ponto[0],
                    lon=ponto[1],
                    status="automatic",
                    lugar=evento.get("title"),
                    metrics=metrics,
                    xrefs={
                        "ids": ids_origem,
                        "fontes_origem": [
                            str(fonte.get("id")) for fonte in fontes if fonte.get("id")
                        ],
                    },
                )
            )
        return observacoes
