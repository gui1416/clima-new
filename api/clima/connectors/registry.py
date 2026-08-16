from __future__ import annotations

from clima.connectors.base import Conector
from clima.connectors.usgs import ConectorUSGS

# Fase 0 coleta uma fonte só. As demais estão registradas em `sources` com
# ativa=false — o registro é honesto sobre o que existe e o que ainda não.
CONECTORES: dict[str, Conector] = {
    c.id: c
    for c in (ConectorUSGS(),)
}


def conector(source_id: str) -> Conector:
    try:
        return CONECTORES[source_id]
    except KeyError:
        raise LookupError(f"sem conector implementado para a fonte {source_id!r}") from None
