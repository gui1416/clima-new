"""Parser do EMSC, contra payload real de 55 sismos.

O teste que mais importa é o do **sinal da profundidade**: o EMSC segue a convenção
GeoJSON de elevação (`coordinates[2] = -35.0` para 35 km de profundidade) enquanto o
USGS usa a terceira coordenada como profundidade positiva. Um parser compartilhado
inverteria o sinal de toda profundidade de uma das duas fontes — e nada acusaria.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clima.connectors.emsc import ConectorEMSC

FIXTURE = Path(__file__).parent / "fixtures" / "emsc-recentes.json"
CORPO = FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def obs():  # noqa: ANN201
    return ConectorEMSC().analisar(CORPO)


def test_extrai_todas_as_features(obs) -> None:  # noqa: ANN001
    assert len(obs) == 55


def test_profundidade_vem_de_properties_nao_da_coordenada(obs) -> None:  # noqa: ANN001
    """A armadilha central. Profundidade tem de sair positiva para baixo."""
    doc = json.loads(CORPO)
    por_id = {o.source_event_id: o for o in obs}

    conferidos = 0
    for f in doc["features"]:
        p = f["properties"]
        if p.get("depth") is None or p["depth"] == 0:
            continue
        o = por_id[str(p["unid"])]
        assert o.profundidade_km == pytest.approx(p["depth"])
        assert o.profundidade_km > 0, "profundidade abaixo do nível do mar é positiva"
        # E precisa ser o oposto da terceira coordenada, que é elevação.
        assert o.profundidade_km == pytest.approx(-f["geometry"]["coordinates"][2])
        conferidos += 1
    assert conferidos > 10, "a fixture deveria ter profundidades para conferir"


def test_timestamps_iso_com_fuso(obs) -> None:  # noqa: ANN001
    """O EMSC manda ISO, não epoch. Tratar como número daria erro silencioso."""
    for o in obs:
        assert o.observed_at.tzinfo is not None
        assert datetime(2020, 1, 1, tzinfo=UTC) < o.observed_at < datetime(2100, 1, 1, tzinfo=UTC)
        assert o.source_updated_at >= o.observed_at


def test_evtype_mapeado_sem_inventar_tipo(obs) -> None:  # noqa: ANN001
    assert {o.event_type for o in obs} == {"earthquake"}
    # Tipo desconhecido é preservado, não convertido em sismo.
    doc = json.loads(CORPO)
    doc["features"] = doc["features"][:1]
    doc["features"][0]["properties"]["evtype"] = "ls"  # deslizamento
    assert ConectorEMSC().analisar(json.dumps(doc).encode())[0].event_type == "ls"


def test_agencia_nao_e_identificador_de_evento(obs) -> None:  # noqa: ANN001
    """`auth` é quem forneceu a solução (BMKG, AFAD…). Se entrasse na interseção de
    xref, todo sismo da mesma agência viraria o mesmo evento."""
    from clima.correlation.motor import identificadores

    from clima.correlation.features import Registro

    def reg(o):  # noqa: ANN001, ANN202
        return Registro(
            id=1, source_id="emsc", source_event_id=o.source_event_id,
            event_type="earthquake", lat=o.lat, lon=o.lon,
            observed_at=o.observed_at, xrefs=o.xrefs,
        )

    mesma_agencia = [o for o in obs if o.xrefs.get("agencia") == obs[0].xrefs.get("agencia")]
    if len(mesma_agencia) > 1:
        a, b = reg(mesma_agencia[0]), reg(mesma_agencia[1])
        assert not identificadores(a) & identificadores(b)


def test_status_nao_afirma_revisao_inexistente(obs) -> None:  # noqa: ANN001
    """O EMSC não distingue automático de revisado. Assumir 'reviewed' inflaria a
    confiança sem base."""
    assert {o.status for o in obs} == {"automatic"}


def test_parser_e_puro() -> None:
    assert ConectorEMSC().analisar(CORPO) == ConectorEMSC().analisar(CORPO)


def test_rejeita_documento_invalido() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        ConectorEMSC().analisar(b'{"type": "Feature"}')
