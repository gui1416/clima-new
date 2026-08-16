"""Conector EMSC, via o serviço FDSN do seismicportal.eu.

Segunda fonte de sismos, e a primeira que dá trabalho real ao motor de correlação:
o EMSC observa de forma independente do USGS, então o mesmo terremoto aparece nas
duas com epicentro, horário e magnitude levemente diferentes — que é exatamente o
problema que o produto existe para resolver.

**Não há cruzamento determinístico com o USGS.** O EMSC traz `auth` (a agência que
forneceu a solução: BMKG, AFAD, CSN…) mas nenhum identificador do USGS. Então o
caminho de xref do §5.2 não dispara aqui, e a decisão fica com o modelo
probabilístico. É o caso honesto e é o que valida o motor.

Três diferenças em relação ao USGS que quebrariam um parser compartilhado:

1. **Sinal da profundidade.** O USGS usa a terceira coordenada GeoJSON como
   profundidade positiva para baixo. O EMSC segue a convenção de elevação —
   `coordinates[2] = -35.0` para 35 km de profundidade — e traz `properties.depth`
   positivo. Ler a terceira coordenada aqui inverteria o sinal de toda profundidade.
2. **Timestamps ISO**, não epoch em milissegundos.
3. **`lastupdate` é o marcador de revisão**, equivalente ao `updated` do USGS.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from clima.connectors.base import Observacao, Resposta, Validadores, resposta_de_httpx

BASE = "https://www.seismicportal.eu/fdsnws/event/1/query"

# Janela sondada a cada coleta. Sobreposição grande de propósito: uma coleta que
# falhe não abre lacuna, porque a seguinte ainda cobre o mesmo intervalo.
JANELA_HORAS = 2

# `evtype` do EMSC. 'ke' = known earthquake, 'se' = suspected earthquake. Outros
# valores (deslizamento, explosão) são preservados como vieram — o produto não deve
# afirmar que um desmoronamento é um sismo.
TIPOS = {"ke": "earthquake", "se": "earthquake"}


def _instante(v: Any) -> datetime | None:
    if not v:
        return None
    # O EMSC às vezes manda segundos fracionários com um dígito e 'Z' no fim.
    texto = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(texto).astimezone(UTC)
    except ValueError:
        return None


class ConectorEMSC:
    id = "emsc"

    def __init__(self, base: str = BASE) -> None:
        self.base = base

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        from datetime import timedelta

        inicio = (datetime.now(UTC) - timedelta(hours=JANELA_HORAS)).strftime("%Y-%m-%dT%H:%M:%S")
        r = await cliente.get(
            self.base,
            params={"format": "json", "starttime": inicio, "limit": 1000, "orderby": "time"},
            headers=anteriores.cabecalhos(),
        )
        return resposta_de_httpx(r)

    def analisar(self, corpo: bytes) -> Sequence[Observacao]:
        doc = json.loads(corpo)
        if doc.get("type") != "FeatureCollection":
            raise ValueError(f"esperava FeatureCollection, veio {doc.get('type')!r}")

        obs: list[Observacao] = []
        for f in doc.get("features", []):
            p = f.get("properties") or {}
            ident = p.get("unid") or f.get("id")
            ocorreu = _instante(p.get("time"))
            if ident is None or ocorreu is None:
                continue
            if p.get("lat") is None or p.get("lon") is None:
                continue

            obs.append(
                Observacao(
                    source_event_id=str(ident),
                    observed_at=ocorreu,
                    source_updated_at=_instante(p.get("lastupdate")) or ocorreu,
                    event_type=TIPOS.get(str(p.get("evtype")), str(p.get("evtype") or "earthquake")),
                    lat=float(p["lat"]),
                    lon=float(p["lon"]),
                    # O EMSC não distingue solução automática de revisada como o
                    # USGS. Assumir 'reviewed' inflaria a confiança sem base.
                    status="automatic",
                    lugar=p.get("flynn_region"),
                    magnitude=None if p.get("mag") is None else float(p["mag"]),
                    # De `properties.depth`, NUNCA de coordinates[2] — ver docstring.
                    profundidade_km=None if p.get("depth") is None else float(p["depth"]),
                    metrics={
                        k: p[k]
                        for k in ("magtype", "auth", "source_catalog", "evtype")
                        if p.get(k) is not None
                    },
                    xrefs={
                        "emsc": str(ident),
                        # Agência que forneceu a solução. Não é identificador de
                        # evento, então não entra na interseção de xref — mas é
                        # informação de procedência.
                        **({"agencia": p["auth"]} if p.get("auth") else {}),
                    },
                )
            )
        return obs
