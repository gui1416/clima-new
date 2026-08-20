from __future__ import annotations

from clima.connectors.base import Conector
from clima.connectors.emsc import ConectorEMSC
from clima.connectors.eonet import ConectorEONET
from clima.connectors.gdacs import ConectorGDACS
from clima.connectors.usgs import ConectorUSGS

CONECTORES: dict[str, Conector] = {
    c.id: c
    for c in (ConectorUSGS(), ConectorEMSC(), ConectorGDACS(), ConectorEONET())
}


def conector(source_id: str) -> Conector:
    try:
        return CONECTORES[source_id]
    except KeyError:
        raise LookupError(f"sem conector implementado para a fonte {source_id!r}") from None
