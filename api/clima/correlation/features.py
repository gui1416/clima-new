"""O vetor de features de um par candidato, e o modelo que o pontua.

Puro: sem banco, sem rede, sem relógio. Toda a decisão de correlação é testável
sem infraestrutura, e o mesmo par sempre dá o mesmo score.

**Regressão logística, deliberadamente.** Um modelo mais forte não melhora nada
enquanto o golden set for pequeno, e este é interpretável: dá para dizer na
interface *por que* dois registros foram unidos, e dá para um humano discordar de
forma fundamentada. Num produto cuja tese é "as fontes discordam entre si", o
motor que resolve a discordância não pode ser uma caixa preta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

# Raio médio da Terra em metros (esfera de mesma área — WGS84 authalic).
RAIO_TERRA_M = 6_371_007.2

# Valor da feature de métrica quando um dos lados não tem a grandeza.
#
# 0,5 e não 0,0 nem 1,0, e a escolha importa. Zero significaria "as magnitudes
# concordam perfeitamente" — ausência de evidência lida como evidência a favor.
# Um significaria "discordam ao máximo" — ausência lida como evidência contra.
# Nenhuma das duas é verdade: não saber fica no meio, e o par decide pelo espaço e
# pelo tempo.
D_METRICA_DESCONHECIDA = 0.5


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Erro < 0,5 % contra o elipsoide, irrelevante nas escalas daqui.

    O PostGIS já faz isso no blocking com precisão geodésica; esta função existe
    para o cálculo de feature ficar puro e testável fora do banco.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_M * math.asin(min(1.0, math.sqrt(a)))


def similaridade_toponimo(a: str | None, b: str | None) -> float:
    """Jaccard sobre tokens, 0 a 1. Sinal fraco de propósito.

    Topônimos divergem entre idiomas e fontes ("Costa de Honshu" vs "off the east
    coast of Honshu, Japan"), e cidades homônimas existem. Serve para desempatar,
    nunca para decidir — daí o peso baixo em `correlation_params`.
    """
    if not a or not b:
        return 0.0
    ta = {t for t in a.lower().replace(",", " ").split() if len(t) > 2}
    tb = {t for t in b.lower().replace(",", " ").split() if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass(frozen=True, slots=True)
class Registro:
    """O mínimo de um `source_record` que a correlação precisa."""

    id: int
    source_id: str
    source_event_id: str
    event_type: str
    lat: float
    lon: float
    observed_at: datetime
    magnitude: float | None = None
    profundidade_km: float | None = None
    lugar: str | None = None
    # 'automatic' | 'reviewed'. Entra no cálculo de confiança da síntese.
    status: str = "automatic"
    xrefs: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class Parametros:
    """Espelha uma linha de `correlation_params`."""

    event_type: str
    raio_m: int
    janela_seg: int
    peso_espaco: float
    peso_tempo: float
    peso_metrica: float
    peso_toponimo: float
    intercepto: float
    limiar_uniao: float
    limiar_duvida: float
    diametro_max_m: int
    diametro_max_seg: int


@dataclass(frozen=True, slots=True)
class Features:
    """Distâncias **normalizadas** pelos limites do tipo, não em unidades brutas.

    Normalizar é o que permite um conjunto de pesos servir para tipos com escalas
    muito diferentes: 50 km é quase nada para um ciclone e é longe para um sismo.
    """

    d_espaco: float  # distância / raio_m       — 0 = mesmo ponto
    d_tempo: float  # |Δt| / janela_seg        — 0 = mesmo instante
    d_metrica: float  # |Δmag| / 1,0            — 1,0 se falta em um dos lados
    sim_toponimo: float
    metrica_comparavel: bool

    def como_dict(self) -> dict[str, float | bool]:
        return {
            "d_espaco": round(self.d_espaco, 4),
            "d_tempo": round(self.d_tempo, 4),
            "d_metrica": round(self.d_metrica, 4),
            "sim_toponimo": round(self.sim_toponimo, 4),
            "metrica_comparavel": self.metrica_comparavel,
        }


def extrair(a: Registro, b: Registro, p: Parametros) -> Features:
    metros = distancia_m(a.lat, a.lon, b.lat, b.lon)
    segundos = abs((a.observed_at - b.observed_at).total_seconds())

    comparavel = a.magnitude is not None and b.magnitude is not None
    if comparavel:
        # 1,0 de diferença de magnitude é muito: redes divergem em ~0,1–0,3.
        d_metrica = min(1.0, abs(a.magnitude - b.magnitude) / 1.0)  # type: ignore[operator]
    else:
        d_metrica = D_METRICA_DESCONHECIDA

    return Features(
        d_espaco=min(1.0, metros / p.raio_m),
        d_tempo=min(1.0, segundos / p.janela_seg),
        d_metrica=d_metrica,
        sim_toponimo=similaridade_toponimo(a.lugar, b.lugar),
        metrica_comparavel=comparavel,
    )


def score(f: Features, p: Parametros) -> float:
    """Probabilidade de os dois registros descreverem o mesmo fenômeno.

    Logit linear nas features normalizadas. Pesos negativos porque as features são
    *distâncias*: quanto maior, menos provável que seja o mesmo evento.
    """
    z = (
        p.intercepto
        + p.peso_espaco * f.d_espaco
        + p.peso_tempo * f.d_tempo
        + p.peso_toponimo * f.sim_toponimo
    )
    # O termo entra SEMPRE. Pulá-lo quando a métrica falta equivaleria a d_metrica
    # = 0, ou seja, a tratar ausência como concordância perfeita — foi o defeito que
    # `test_metrica_ausente_nao_conta_como_concordancia` pegou. A ausência entra com
    # D_METRICA_DESCONHECIDA, que fica entre concordar e discordar.
    z += p.peso_metrica * f.d_metrica
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))


def veredito(s: float, p: Parametros) -> str:
    """Três estados, não dois.

    Falso merge esconde um evento real; falso split só repete informação. Então a
    faixa do meio não vira palpite — vira `incerto` e vai para revisão humana.
    """
    if s >= p.limiar_uniao:
        return "mesmo"
    if s >= p.limiar_duvida:
        return "incerto"
    return "distinto"


def explicar(f: Features, p: Parametros) -> list[str]:
    """Por que o par pontuou assim, em pt-BR. Vai para a interface de revisão."""
    partes = [
        f"{f.d_espaco * p.raio_m / 1000:.1f} km de distância "
        f"(limite do tipo: {p.raio_m / 1000:.0f} km)",
        f"{f.d_tempo * p.janela_seg:.0f} s de diferença "
        f"(janela: {p.janela_seg} s)",
    ]
    if f.metrica_comparavel:
        partes.append(f"magnitudes diferem em {f.d_metrica:.2f}")
    else:
        partes.append("métrica ausente em um dos lados — não entrou no cálculo")
    if f.sim_toponimo > 0:
        partes.append(f"topônimos com {f.sim_toponimo:.0%} de sobreposição")
    return partes
