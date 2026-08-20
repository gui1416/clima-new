"""Conector GDACS para terremotos significativos.

O feed repete cada episódio como centróide e como polígonos de alcance. Só o
centróide representa a observação; aceitar os polígonos criaria duplicatas do
mesmo ``eventid`` dentro do próprio payload.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from clima.connectors.base import Observacao, Resposta, Validadores, resposta_de_httpx

FEED = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP?eventtype=EQ"


def _instante(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        instante = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=UTC)
        return instante.astimezone(UTC)
    except ValueError:
        return None


def _profundidade(texto: Any) -> float | None:
    if not isinstance(texto, str):
        return None
    achado = re.search(r"Depth:\s*(-?[0-9]+(?:\.[0-9]+)?)\s*km", texto, re.I)
    return float(achado.group(1)) if achado else None


class ConectorGDACS:
    id = "gdacs"

    def __init__(self, url: str = FEED) -> None:
        self.url = url

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        resposta = await cliente.get(self.url, headers=anteriores.cabecalhos())
        return resposta_de_httpx(resposta)

    def analisar(self, corpo: bytes) -> Sequence[Observacao]:
        doc = json.loads(corpo)
        if doc.get("type") != "FeatureCollection":
            raise ValueError(f"esperava FeatureCollection, veio {doc.get('type')!r}")

        observacoes: list[Observacao] = []
        vistos: set[str] = set()
        for feature in doc.get("features", []):
            propriedades = feature.get("properties") or {}
            geometria = feature.get("geometry") or {}
            coordenadas = geometria.get("coordinates") or []
            evento_id = propriedades.get("eventid")
            ocorreu = _instante(propriedades.get("fromdate"))
            revisado = _instante(propriedades.get("datemodified")) or ocorreu
            if (
                evento_id is None
                or str(evento_id) in vistos
                or geometria.get("type") != "Point"
                or len(coordenadas) < 2
                or ocorreu is None
                or revisado is None
            ):
                continue

            vistos.add(str(evento_id))
            severidade = propriedades.get("severitydata") or {}
            source_id = propriedades.get("sourceid")
            glide = propriedades.get("glide")
            xrefs: dict[str, object] = {"gdacs": str(evento_id)}
            if propriedades.get("source") == "NEIC" and source_id:
                xrefs["usgs"] = str(source_id)
            if glide:
                xrefs["glide"] = str(glide)

            observacoes.append(
                Observacao(
                    source_event_id=str(evento_id),
                    observed_at=ocorreu,
                    source_updated_at=revisado,
                    event_type="earthquake",
                    lat=float(coordenadas[1]),
                    lon=float(coordenadas[0]),
                    status="automatic",
                    lugar=propriedades.get("name") or propriedades.get("country"),
                    magnitude=(
                        float(severidade["severity"])
                        if severidade.get("severity") is not None
                        else None
                    ),
                    profundidade_km=_profundidade(severidade.get("severitytext")),
                    metrics={
                        chave: propriedades[chave]
                        for chave in ("alertlevel", "alertscore", "episodeid", "iso3")
                        if propriedades.get(chave) is not None
                    },
                    xrefs=xrefs,
                )
            )
        return observacoes
