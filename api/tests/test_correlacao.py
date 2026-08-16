"""O motor de correlação, testado sem banco porque a decisão é função pura.

O caso que mais importa é o **negativo real**: dois sismos distintos a 0,5 km e
62 s um do outro, extraídos do dado que a coleta trouxe. Eles caem dentro da
janela de blocking (100 km / ±90 s), então um motor ingênuo os funde. Precisão
importa mais que recall aqui: unir dois eventos distintos esconde um evento real
do usuário, enquanto deixar duplicatas apenas repete informação.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clima.correlation.clustering import agrupar, diametro
from clima.correlation.features import (
    Parametros,
    Registro,
    distancia_m,
    extrair,
    score,
    similaridade_toponimo,
    veredito,
)
from clima.correlation.motor import identificadores
from clima.correlation.sintese import confianca, sintetizar

# Espelha a linha de correlation_params para 'earthquake' da migration 005.
SISMO = Parametros(
    event_type="earthquake",
    raio_m=100_000,
    janela_seg=90,
    peso_espaco=-4.0,
    peso_tempo=-5.5,
    peso_metrica=-3.0,
    peso_toponimo=0.8,
    intercepto=5.2,
    limiar_uniao=0.90,
    limiar_duvida=0.60,
    diametro_max_m=150_000,
    diametro_max_seg=120,
)

T0 = datetime(2026, 8, 16, 21, 6, 7, tzinfo=UTC)


def reg(
    id_: int,
    fonte: str,
    lat: float,
    lon: float,
    dt_seg: float = 0.0,
    mag: float | None = 4.5,
    lugar: str | None = "105 km W of San Antonio de los Cobres, Argentina",
    xrefs: dict[str, object] | None = None,
    status: str = "automatic",
) -> Registro:
    return Registro(
        id=id_,
        source_id=fonte,
        source_event_id=f"{fonte}-{id_}",
        event_type="earthquake",
        lat=lat,
        lon=lon,
        observed_at=T0 + timedelta(seconds=dt_seg),
        magnitude=mag,
        profundidade_km=164.6,
        lugar=lugar,
        status=status,
        xrefs=xrefs or {},
    )


# ── geometria ──────────────────────────────────────────────────────────────


def test_distancia_conhecida() -> None:
    """Um grau de latitude no equador é ~111,2 km."""
    assert 110_000 < distancia_m(0, 0, 1, 0) < 112_000
    assert distancia_m(-24.3, -67.35, -24.3, -67.35) == 0


def test_similaridade_toponimo() -> None:
    a = "105 km W of San Antonio de los Cobres, Argentina"
    b = "110 km WNW of San Antonio de los Cobres, Argentina"
    assert similaridade_toponimo(a, b) > 0.5
    assert similaridade_toponimo(a, "9 km W of Rincón, Puerto Rico") < 0.15
    # Ausência não é semelhança.
    assert similaridade_toponimo(None, a) == 0.0


# ── o negativo real, que é o teste central ─────────────────────────────────


def test_nao_funde_sismos_distintos_muito_proximos() -> None:
    """Caso extraído do dado coletado: 0,5 km e 62 s de separação.

    Dois sismos genuinamente distintos de um enxame. Estão dentro da janela de
    blocking, logo viram candidatos — e o motor precisa recusá-los. É o caso que
    separa "deduplicar" de "perder evento".
    """
    a = reg(1, "usgs", 35.7773, -117.5968, mag=1.06, lugar="17 km W of Searles Valley, CA")
    b = reg(2, "usgs", 35.7818, -117.5945, dt_seg=62, mag=0.65,
            lugar="18 km W of Searles Valley, CA")

    f = extrair(a, b, SISMO)
    assert f.d_espaco < 0.01, "estão a meio quilômetro — o espaço não os separa"
    assert f.d_tempo > 0.65, "62 s de 90 s de janela: é o tempo que os separa"

    s = score(f, SISMO)
    assert veredito(s, SISMO) != "mesmo", f"fundiu eventos distintos (score {s:.3f})"


def test_o_mesmo_sismo_por_duas_redes_e_unido() -> None:
    """Duas redes reportando o mesmo evento: epicentro e magnitude divergem pouco,
    o horário de origem quase não. É o positivo que o motor precisa aceitar."""
    a = reg(1, "usgs", -24.3051, -67.3517, mag=4.5)
    # Deslocamento típico entre agências: ~12 km, 1,5 s, 0,2 de magnitude.
    b = reg(2, "emsc", -24.3980, -67.4200, dt_seg=1.5, mag=4.3)

    s = score(extrair(a, b, SISMO), SISMO)
    assert veredito(s, SISMO) == "mesmo", f"não uniu o mesmo evento (score {s:.3f})"


def test_tempo_discrimina_mais_que_espaco_em_sismo() -> None:
    """Decisão de calibração: o horário de origem é preciso, o epicentro não.

    Mesmo ponto com 80 s de diferença deve pontuar menos que 60 km com 1 s.
    """
    mesmo_lugar_tarde = score(
        extrair(reg(1, "a", 0, 0), reg(2, "b", 0, 0, dt_seg=80), SISMO), SISMO
    )
    longe_mas_simultaneo = score(
        extrair(reg(1, "a", 0, 0), reg(2, "b", 0.54, 0, dt_seg=1), SISMO), SISMO
    )
    assert mesmo_lugar_tarde < longe_mas_simultaneo


def test_metrica_ausente_nao_conta_como_concordancia() -> None:
    com = score(extrair(reg(1, "a", 0, 0, mag=4.5), reg(2, "b", 0, 0, mag=4.5), SISMO), SISMO)
    sem = score(extrair(reg(1, "a", 0, 0, mag=None), reg(2, "b", 0, 0, mag=4.5), SISMO), SISMO)
    assert sem < com, "faltar magnitude não pode valer o mesmo que magnitudes iguais"


def test_faixa_de_duvida_existe() -> None:
    """Três estados, não dois: o meio vira revisão humana em vez de palpite."""
    assert veredito(0.95, SISMO) == "mesmo"
    assert veredito(0.75, SISMO) == "incerto"
    assert veredito(0.30, SISMO) == "distinto"


# ── cruzamento determinístico ──────────────────────────────────────────────


def test_xref_liga_registros_de_fontes_diferentes() -> None:
    a = reg(1, "usgs", 0, 0, xrefs={"usgs": "us7000abcd"})
    b = reg(2, "gdacs", 5, 5, xrefs={"gdacs": "g123", "redes": ["us7000abcd"]})
    assert identificadores(a) & identificadores(b) == {"us7000abcd"}


def test_nome_de_rede_nao_e_identificador_de_evento() -> None:
    """`contribuintes` lista redes ('nc', 'ci'), não eventos. Tratá-las como
    identificador fundiria todo sismo reportado pela mesma rede."""
    a = reg(1, "usgs", 0, 0, xrefs={"usgs": "nc111", "contribuintes": ["nc"]})
    b = reg(2, "usgs", 40, 40, xrefs={"usgs": "nc222", "contribuintes": ["nc"]})
    assert not identificadores(a) & identificadores(b)


# ── clustering e a guarda de encadeamento ──────────────────────────────────


def test_encadeamento_nao_funde_cluster_esticado() -> None:
    """A~B e B~C, mas A e C distantes: união cega criaria um evento inexistente.

    O cluster estoura o diâmetro do tipo e é desfeito por inteiro, com os pares
    rebaixados para revisão — em vez de escolher qual aresta cortar sem evidência.
    """
    a = reg(1, "x", 0.0, 0.0)
    b = reg(2, "y", 0.8, 0.0)  # ~89 km de a
    c = reg(3, "z", 1.6, 0.0)  # ~178 km de a: acima do diâmetro de 150 km
    registros = {r.id: r for r in (a, b, c)}

    res = agrupar(registros, [(1, 2), (2, 3)], SISMO)

    assert diametro([a, b, c]).metros > SISMO.diametro_max_m
    assert all(len(cl) == 1 for cl in res.clusters), "cluster esticado deveria ser desfeito"
    assert set(res.rejeitados_por_diametro) == {(1, 2), (2, 3)}


def test_cluster_dentro_do_diametro_e_mantido() -> None:
    a = reg(1, "x", 0.0, 0.0)
    b = reg(2, "y", 0.2, 0.0)  # ~22 km
    res = agrupar({1: a, 2: b}, [(1, 2)], SISMO)
    assert [sorted(r.id for r in cl) for cl in res.clusters] == [[1, 2]]
    assert not res.rejeitados_por_diametro


def test_registro_sem_par_vira_evento_proprio() -> None:
    a = reg(1, "x", 0, 0)
    res = agrupar({1: a}, [], SISMO)
    assert [len(cl) for cl in res.clusters] == [1]


# ── síntese ────────────────────────────────────────────────────────────────


def test_precedencia_por_campo_nunca_media() -> None:
    """A magnitude adotada é a de uma fonte, não a média das duas.

    Média de magnitudes de duas redes não é uma magnitude: é um número que ninguém
    mediu, apresentado com autoridade de medição.
    """
    usgs = reg(1, "usgs", -24.30, -67.35, mag=4.5)
    gdacs = reg(2, "gdacs", -24.40, -67.40, mag=4.9, lugar="Salta, Argentina")

    c = sintetizar([gdacs, usgs])

    assert c.magnitude == 4.5, "USGS tem precedência em magnitude"
    assert c.magnitude != pytest.approx((4.5 + 4.9) / 2)
    assert (c.lat, c.lon) == (-24.30, -67.35), "USGS tem precedência em epicentro"
    assert c.lugar == "Salta, Argentina", "GDACS tem precedência em topônimo"
    assert c.source_count == 2


def test_divergencia_e_preservada_como_afirmacoes() -> None:
    """Toda fonte tem sua afirmação registrada, com marca de qual venceu.

    É a base do painel de procedência — e esconder isso repetiria o problema que o
    produto existe para resolver.
    """
    usgs = reg(1, "usgs", 0, 0, mag=4.5)
    gdacs = reg(2, "gdacs", 0.1, 0.1, mag=4.9)
    c = sintetizar([usgs, gdacs])

    mags = {a.source_id: a.valor for a in c.afirmacoes if a.campo == "magnitude"}
    assert mags == {"usgs": 4.5, "gdacs": 4.9}, "as duas magnitudes precisam sobreviver"

    vencedores = [a.source_id for a in c.afirmacoes if a.campo == "magnitude" and a.vencedor]
    assert vencedores == ["usgs"]
    assert c.divergencias["magnitude"] == pytest.approx(0.4, abs=0.01)


def test_confianca_sobe_com_fontes_e_cai_com_discordancia() -> None:
    """Duas confirmações independentes valem mais que uma, mesmo discordando.

    Uma versão anterior deste teste exigia que duas fontes em discordância
    pontuassem **abaixo** de uma fonte sozinha. Estava errado: elas discordam sobre
    a magnitude, não sobre a ocorrência — e a existência do evento é a pergunta
    primária. Discordância derruba a confiança em relação a duas fontes
    concordantes, e só fura o piso de uma fonte quando é extrema.
    """
    uma = confianca([reg(1, "usgs", 0, 0)], {})
    duas = confianca([reg(1, "usgs", 0, 0), reg(2, "gdacs", 0, 0)], {})
    duas_discordando = confianca(
        [reg(1, "usgs", 0, 0), reg(2, "gdacs", 0, 0)], {"magnitude": 0.9}
    )

    assert uma < duas, "mais fontes independentes é mais confiança"
    assert duas_discordando < duas, "discordar precisa custar"
    assert uma < duas_discordando, "mas duas detecções ainda confirmam melhor que uma"
    assert duas <= 0.95, "nenhuma quantidade de fontes justifica afirmar certeza"


def test_discordancia_extrema_derruba_abaixo_de_uma_fonte() -> None:
    """Quando as fontes divergem ao máximo em tudo, a consolidação informa menos
    que um registro isolado — e a confiança precisa refletir isso."""
    uma = confianca([reg(1, "usgs", 0, 0)], {})
    caotico = confianca(
        [reg(1, "usgs", 0, 0), reg(2, "gdacs", 0, 0)],
        {"magnitude": 1.0, "profundidade_km": 1.0},
    )
    assert caotico < uma


def test_revisado_por_analista_pesa_na_confianca() -> None:
    auto = confianca([reg(1, "usgs", 0, 0, status="automatic")], {})
    revisado = confianca([reg(1, "usgs", 0, 0, status="reviewed")], {})
    assert revisado > auto


def test_chave_do_cluster_e_estavel_na_ordem_dos_membros() -> None:
    """Idempotência: reconstruir o cluster não pode criar evento canônico novo."""
    a = reg(1, "usgs", 0, 0)
    b = reg(2, "gdacs", 0.1, 0.1)
    assert sintetizar([a, b]).cluster_key == sintetizar([b, a]).cluster_key


def test_cluster_vazio_e_erro() -> None:
    with pytest.raises(ValueError, match="vazio"):
        sintetizar([])


def test_chave_desconhecida_em_xrefs_nao_vira_identificador() -> None:
    """Allowlist, não blocklist. Uma fonte nova que traga `{'operador': 'X'}` não pode
    fazer todos os eventos dela colapsarem num só — e uma blocklist deixaria passar.
    """
    a = reg(1, "nova", 0, 0, xrefs={"operador": "X", "nova": "n1"})
    b = reg(2, "nova", 40, 40, xrefs={"operador": "X", "nova": "n2"})
    assert not identificadores(a) & identificadores(b)


def test_agencia_do_emsc_nao_vira_identificador() -> None:
    a = reg(1, "emsc", 0, 0, xrefs={"emsc": "e1", "agencia": "BMKG"})
    b = reg(2, "emsc", 40, 40, xrefs={"emsc": "e2", "agencia": "BMKG"})
    assert not identificadores(a) & identificadores(b)
