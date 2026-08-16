from __future__ import annotations

from clima.connectors.base import Conector
from clima.connectors.emsc import ConectorEMSC
from clima.connectors.usgs import ConectorUSGS

# Duas fontes de sismo, que é o mínimo para o motor de correlação ter trabalho.
# As demais estão registradas em `sources` com ativa=false — o registro é honesto
# sobre o que existe e o que ainda não.
CONECTORES: dict[str, Conector] = {
    c.id: c
    for c in (ConectorUSGS(), ConectorEMSC())
}


def conector(source_id: str) -> Conector:
    try:
        return CONECTORES[source_id]
    except KeyError:
        raise LookupError(f"sem conector implementado para a fonte {source_id!r}") from None
