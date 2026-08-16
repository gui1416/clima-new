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

import httpx

from clima.connectors.base import Resposta, Validadores, resposta_de_httpx

FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"


class ConectorUSGS:
    id = "usgs"

    def __init__(self, url: str = FEED) -> None:
        self.url = url

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        r = await cliente.get(self.url, headers=anteriores.cabecalhos())
        return resposta_de_httpx(r)
