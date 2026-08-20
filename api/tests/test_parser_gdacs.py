from __future__ import annotations

from pathlib import Path

import pytest

from clima.connectors.gdacs import ConectorGDACS
from clima.correlation.features import Registro
from clima.correlation.motor import identificadores

CORPO = (Path(__file__).parent / "fixtures" / "gdacs-amostra.json").read_bytes()


def test_gdacs_descarta_poligono_duplicado_e_extrai_sismo() -> None:
    observacoes = ConectorGDACS().analisar(CORPO)
    assert len(observacoes) == 1
    o = observacoes[0]
    assert o.source_event_id == "1560289"
    assert o.event_type == "earthquake"
    assert o.magnitude == 5.5
    assert o.profundidade_km == 10
    assert o.xrefs["usgs"] == "us6000tlxq"


def test_gdacs_cruza_deterministicamente_com_usgs() -> None:
    o = ConectorGDACS().analisar(CORPO)[0]
    gdacs = Registro(
        id=1, source_id="gdacs", source_event_id=o.source_event_id,
        event_type=o.event_type, lat=o.lat, lon=o.lon,
        observed_at=o.observed_at, xrefs=o.xrefs,
    )
    usgs = Registro(
        id=2, source_id="usgs", source_event_id="us6000tlxq",
        event_type="earthquake", lat=o.lat, lon=o.lon,
        observed_at=o.observed_at, xrefs={"usgs": "us6000tlxq"},
    )
    assert identificadores(gdacs) & identificadores(usgs) == {"us6000tlxq"}


def test_gdacs_rejeita_formato_invalido() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        ConectorGDACS().analisar(b'{"type":"Feature"}')
