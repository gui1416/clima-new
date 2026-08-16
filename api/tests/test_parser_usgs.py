"""O parser do USGS, contra um payload real gravado pela própria coleta.

Fixture é resposta de verdade de `all_hour.geojson`, não JSON inventado: 11 sismos,
magnitudes de 0,43 a 2,78, `status` misturando 'automatic' e 'reviewed'. Testar
contra dado sintético esconderia exatamente as peculiaridades que quebram parser —
o `ids` delimitado por vírgula nas duas pontas, o epoch em milissegundos, a
profundidade negativa em evento raso.

Roda sem infraestrutura: o parser é puro, por contrato.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clima.connectors.usgs import ConectorUSGS, _lista

FIXTURE = Path(__file__).parent / "fixtures" / "usgs-all-hour.json"
CORPO = FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def obs():  # noqa: ANN201
    return ConectorUSGS().analisar(CORPO)


def test_extrai_todas_as_features(obs) -> None:  # noqa: ANN001
    assert len(obs) == 11


def test_epoch_em_milissegundos(obs) -> None:  # noqa: ANN001
    """O USGS usa ms. Tratar como segundos jogaria tudo para 1970."""
    for o in obs:
        assert o.observed_at.tzinfo is not None
        assert datetime(2020, 1, 1, tzinfo=UTC) < o.observed_at < datetime(2100, 1, 1, tzinfo=UTC)
        # `updated` nunca antecede `time`.
        assert o.source_updated_at >= o.observed_at


def test_coordenadas_e_profundidade(obs) -> None:  # noqa: ANN001
    for o in obs:
        assert -90 <= o.lat <= 90
        assert -180 <= o.lon <= 180
    # A terceira coordenada é profundidade em km, e pode ser negativa em evento
    # raso — acima do nível do mar. Descartar negativo perderia dado real.
    assert any(o.profundidade_km is not None and o.profundidade_km < 0 for o in obs)


def test_lista_delimitada_por_virgula() -> None:
    """`,nc75419652,` — vírgula nas duas pontas. Split ingênuo devolve vazios."""
    assert _lista(",nc75419652,") == ["nc75419652"]
    assert _lista(",nc123,ci456,") == ["nc123", "ci456"]
    assert _lista("") == []
    assert _lista(None) == []


def test_xrefs_carregam_o_identificador_da_fonte(obs) -> None:  # noqa: ANN001
    """A via determinística do §5.2: sem xref, a Fase 2 vira só probabilística."""
    for o in obs:
        assert o.xrefs["usgs"] == o.source_event_id
        assert "contribuintes" in o.xrefs  # redes que reportaram
        assert all(isinstance(r, str) and r for r in o.xrefs["contribuintes"])


def test_status_da_fonte_e_preservado(obs) -> None:  # noqa: ANN001
    """'automatic' vs 'reviewed' é insumo de confiança; achatar isso perde sinal."""
    assert {o.status for o in obs} <= {"automatic", "reviewed", "deleted"}
    assert len({o.status for o in obs}) >= 2, "a fixture deveria ter os dois status"


def test_metricas_de_qualidade_preservadas(obs) -> None:  # noqa: ANN001
    algum = next(o for o in obs if o.metrics)
    assert "magType" in algum.metrics or "nst" in algum.metrics


def test_parser_e_puro_e_deterministico() -> None:
    """Duas chamadas com os mesmos bytes dão o mesmo resultado.

    É o que permite replay: reanalisar o histórico não pode depender de relógio,
    rede ou estado.
    """
    a = ConectorUSGS().analisar(CORPO)
    b = ConectorUSGS().analisar(CORPO)
    assert a == b


def test_rejeita_documento_que_nao_e_colecao() -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        ConectorUSGS().analisar(b'{"type": "Feature"}')


def test_ignora_feature_sem_geometria_utilizavel() -> None:
    doc = json.loads(CORPO)
    doc["features"][0]["geometry"]["coordinates"] = []
    assert len(ConectorUSGS().analisar(json.dumps(doc).encode())) == 10


def test_ignora_feature_sem_id() -> None:
    doc = json.loads(CORPO)
    del doc["features"][0]["id"]
    assert len(ConectorUSGS().analisar(json.dumps(doc).encode())) == 10


def test_titulo_arredonda_como_o_navegador() -> None:
    """M 2,65 tem de sair 2,7 aqui e no Intl do navegador — o mesmo número não pode
    aparecer de dois jeitos na mesma linha da tabela."""
    from clima.api.eventos import _titulo

    assert _titulo("x", 2.65, "earthquake") == "Sismo M 2,7"
    assert _titulo("x", 2.64, "earthquake") == "Sismo M 2,6"
    assert _titulo("x", 4.5, "earthquake") == "Sismo M 4,5"
    assert _titulo("x", None, "earthquake") == "Sismo — x"
