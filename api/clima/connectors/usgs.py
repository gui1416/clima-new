"""Conector USGS. Fase 0: só coleta.

Feed escolhido: ``all_hour``, que traz os sismos da última hora inteira, sondado
a cada 60 s. A sobreposição é enorme e proposital — uma coleta que falhe não abre
lacuna no dado, porque a seguinte ainda cobre o mesmo intervalo. Um feed mais
justo (``all_15min``, se houvesse) economizaria banda e criaria buracos.

Na Fase 1, o parser deste conector extrai de ``properties.ids`` os
identificadores de todas as redes contribuintes do mesmo sismo. É a via de
cruzamento determinístico do §5.2 do plano: onde há xref, o vínculo é certo e
não passa pelo caminho probabilístico. Confirmar o formato real do campo contra
a resposta gravada antes de escrever o parser.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from clima.connectors.base import Observacao, Resposta, Validadores, resposta_de_httpx

FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"

# Numéricas de qualidade da solução sismológica. Guardadas porque são o insumo de
# confiança da Fase 2 — quantas estações, abertura azimutal, resíduo — e porque
# `sig` é score composto do próprio USGS e não deve ser confundido com medida
# física (ver a ressalva do score no CLAUDE.md).
METRICAS = ("nst", "gap", "rms", "dmin", "sig", "mmi", "cdi", "felt", "tsunami")


def _de_ms(ms: Any) -> datetime | None:
    """Epoch em milissegundos → datetime UTC. O USGS usa ms, não segundos."""
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


def _lista(campo: Any) -> list[str]:
    """``,nc75419652,ci12345,`` → ``['nc75419652', 'ci12345']``.

    O USGS delimita com vírgula nas duas pontas, então split ingênuo devolve
    strings vazias. Confirmado contra payload real.
    """
    if not isinstance(campo, str):
        return []
    return [p for p in campo.strip(",").split(",") if p]


class ConectorUSGS:
    """Fase 0: coleta. Fase 1: análise.

    Feed escolhido: ``all_hour``, sondado a cada 60 s. A sobreposição é enorme e
    proposital — uma coleta que falhe não abre lacuna, porque a seguinte ainda
    cobre o mesmo intervalo.
    """

    id = "usgs"

    def __init__(self, url: str = FEED) -> None:
        self.url = url

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        r = await cliente.get(self.url, headers=anteriores.cabecalhos())
        return resposta_de_httpx(r)

    def analisar(self, corpo: bytes) -> Sequence[Observacao]:
        doc = json.loads(corpo)
        if doc.get("type") != "FeatureCollection":
            raise ValueError(f"esperava FeatureCollection, veio {doc.get('type')!r}")

        obs: list[Observacao] = []
        for f in doc.get("features", []):
            p = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2 or f.get("id") is None:
                continue

            ocorreu = _de_ms(p.get("time"))
            revisado = _de_ms(p.get("updated")) or ocorreu
            if ocorreu is None or revisado is None:
                continue

            # `ids` traz os identificadores de todas as redes contribuintes do
            # mesmo sismo, e `sources` as redes. É a via de cruzamento
            # determinístico do §5.2: onde há xref, o vínculo é certo e não passa
            # pelo caminho probabilístico.
            xrefs: dict[str, object] = {"usgs": f["id"]}
            if outros := [i for i in _lista(p.get("ids")) if i != f["id"]]:
                xrefs["redes"] = outros
            if redes := _lista(p.get("sources")):
                xrefs["contribuintes"] = redes

            obs.append(
                Observacao(
                    source_event_id=str(f["id"]),
                    observed_at=ocorreu,
                    source_updated_at=revisado,
                    # O feed é só de sismos, mas traz `type` ('earthquake',
                    # 'quarry blast'…). Preservado para não afirmar mais do que a
                    # fonte disse.
                    event_type=str(p.get("type") or "earthquake"),
                    lat=float(coords[1]),
                    lon=float(coords[0]),
                    # 'automatic' | 'reviewed' | 'deleted' — importa para confiança.
                    status=str(p.get("status") or "automatic"),
                    lugar=p.get("place"),
                    magnitude=None if p.get("mag") is None else float(p["mag"]),
                    # Terceira coordenada é profundidade em km; negativa = acima do
                    # nível do mar, o que acontece de verdade em eventos rasos.
                    profundidade_km=float(coords[2]) if len(coords) > 2 else None,
                    metrics={
                        k: p[k] for k in METRICAS if p.get(k) is not None
                    }
                    | ({"magType": p["magType"]} if p.get("magType") else {}),
                    xrefs=xrefs,
                )
            )
        return obs
