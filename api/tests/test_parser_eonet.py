from __future__ import annotations

from pathlib import Path

import pytest

from clima.connectors.eonet import ConectorEONET

CORPO = (Path(__file__).parent / "fixtures" / "eonet-amostra.json").read_bytes()


def test_eonet_usa_geometria_mais_recente_e_metrica_fisica() -> None:
    observacoes = ConectorEONET().analisar(CORPO)
    incendio = observacoes[0]
    assert incendio.event_type == "wildfire"
    assert incendio.lat == pytest.approx(45.8358)
    assert incendio.lon == pytest.approx(-109.52349)
    assert incendio.metrics["magnitude_valor"] == 1000
    assert incendio.metrics["magnitude_unidade"] == "acres"
    assert incendio.xrefs["ids"] == ["2026-MTLG32-261150"]


def test_eonet_reduz_poligono_a_centroide_sem_inventar_magnitude() -> None:
    enchente = ConectorEONET().analisar(CORPO)[1]
    assert enchente.event_type == "flood"
    assert enchente.lat == pytest.approx(-9.2)
    assert enchente.lon == pytest.approx(-49.2)
    assert enchente.magnitude is None


def test_eonet_rejeita_formato_invalido() -> None:
    with pytest.raises(ValueError, match=r"events\[\]"):
        ConectorEONET().analisar(b'{"events":null}')
