"""Cluster → evento canônico, com a divergência preservada.

Duas regras, e as duas são posições de produto, não detalhes de implementação.

**Precedência por campo, nunca média.** A média das magnitudes de duas redes
sismográficas não é uma magnitude — é um número que ninguém mediu, apresentado com
a autoridade de uma medição. Cada campo tem uma ordem de precedência de fonte
declarada, e o valor adotado é de *uma* fonte.

**Divergência é produto.** Todo valor de toda fonte vira `event_field_claims`, com
marca de qual venceu. Esconder a discordância seria repetir exatamente o problema
que o produto existe para resolver: cinco fontes que discordam e ninguém sabe no
quê.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from clima.correlation.features import Registro

# Ordem de precedência por campo. Fonte mais à esquerda ganha quando presente.
#
# Fundamento, não gosto: o USGS é a autoridade sismológica para epicentro e
# magnitude — é quem opera a rede e revisa a solução. O GDACS agrega e é melhor em
# exposição populacional, porque é o que ele calcula. Agência nacional ganha em
# geometria de área afetada, porque tem o cadastro local.
#
# Em configuração e não em tabela porque hoje há uma fonte; quando houver várias e
# a ordem passar a ser objeto de discussão operacional, vira migration.
PRECEDENCIA: dict[str, tuple[str, ...]] = {
    "geom": ("usgs", "emsc", "gdacs"),
    "observed_at": ("usgs", "emsc", "gdacs"),
    "magnitude": ("usgs", "emsc", "gdacs"),
    "profundidade_km": ("usgs", "emsc", "gdacs"),
    "lugar": ("gdacs", "usgs", "emsc"),
    "exposicao": ("gdacs", "copernicus_ems"),
}

CAMPOS_SINTETIZADOS = ("geom", "observed_at", "magnitude", "profundidade_km", "lugar")


@dataclass(frozen=True, slots=True)
class Afirmacao:
    campo: str
    source_id: str
    source_record_id: int
    valor: Any
    vencedor: bool


@dataclass
class Canonico:
    cluster_key: str
    event_type: str
    lat: float
    lon: float
    observed_at: datetime
    lugar: str | None
    magnitude: float | None
    profundidade_km: float | None
    source_count: int
    confianca: float
    status: str
    first_seen: datetime
    last_seen: datetime
    membros: list[Registro]
    afirmacoes: list[Afirmacao] = field(default_factory=list)
    divergencias: dict[str, float] = field(default_factory=dict)


def _ordem(campo: str, source_id: str) -> int:
    """Posição da fonte na precedência do campo; desconhecida vai para o fim."""
    lista = PRECEDENCIA.get(campo, ())
    return lista.index(source_id) if source_id in lista else len(lista)


def _valor(r: Registro, campo: str) -> Any:
    if campo == "geom":
        return [round(r.lat, 5), round(r.lon, 5)]
    if campo == "observed_at":
        return r.observed_at.isoformat()
    return getattr(r, campo, None)


def _escolher(membros: list[Registro], campo: str) -> Registro | None:
    """Primeiro membro com valor presente, na ordem de precedência do campo."""
    candidatos = [m for m in membros if _valor(m, campo) is not None]
    if not candidatos:
        return None
    return min(candidatos, key=lambda m: (_ordem(campo, m.source_id), m.source_id, m.id))


def confianca(membros: list[Registro], divergencias: dict[str, float]) -> float:
    """0 a 1. Sobe com número de fontes independentes, desce com discordância.

    **Não é o score composto** que o CLAUDE.md restringe: não compara categorias de
    evento nem pesa grandezas incomensuráveis. Mede quão bem as fontes concordam
    sobre *este* evento, e por isso sempre aparece com `source_count` ao lado.
    """
    fontes = {m.source_id for m in membros}
    # Uma fonte: 0,55. Duas: 0,75. Três: 0,85. Satura perto de 0,95 — nenhuma
    # quantidade de fontes concordantes justifica afirmar certeza.
    base = min(0.95, 1.0 - 0.45 / len(fontes) ** 0.85)

    revisados = sum(1 for m in membros if m.status == "reviewed")
    if revisados:
        base = min(0.97, base + 0.03 * revisados / len(membros))

    if divergencias:
        # Discordância entre fontes derruba a confiança, e é o comportamento certo:
        # duas fontes que discordam informam menos que uma sozinha.
        base -= min(0.35, sum(divergencias.values()) * 0.15)

    return round(max(0.05, base), 3)


def sintetizar(membros: list[Registro]) -> Canonico:
    if not membros:
        raise ValueError("cluster vazio")

    # Rótulo derivado da observação mais antiga, não da ordem alfabética de fonte.
    # Ordenar por `source_id` fazia a chave trocar quando entrava membro de fonte
    # "menor" — e como a chave era a identidade, isso criava evento novo e orfanava
    # o histórico. Hoje a identidade vem dos membros (ver motor._resolver_evento) e
    # esta chave é só rótulo; ancorá-la no mais antigo a torna estável de todo modo.
    ordenados = sorted(membros, key=lambda m: (m.observed_at, m.source_id, m.source_event_id))
    chave = f"{ordenados[0].source_id}:{ordenados[0].source_event_id}"

    afirmacoes: list[Afirmacao] = []
    escolhidos: dict[str, Registro] = {}

    for campo in CAMPOS_SINTETIZADOS:
        vencedor = _escolher(membros, campo)
        if vencedor is None:
            continue
        escolhidos[campo] = vencedor
        for m in membros:
            v = _valor(m, campo)
            if v is None:
                continue
            afirmacoes.append(
                Afirmacao(
                    campo=campo,
                    source_id=m.source_id,
                    source_record_id=m.id,
                    valor=v,
                    vencedor=m.id == vencedor.id,
                )
            )

    # Divergência numérica normalizada, por campo comparável. É o que alimenta a
    # confiança e o painel de procedência.
    divergencias: dict[str, float] = {}
    for campo, escala in (("magnitude", 1.0), ("profundidade_km", 50.0)):
        vals = [getattr(m, campo) for m in membros if getattr(m, campo, None) is not None]
        if len(vals) > 1 and (spread := max(vals) - min(vals)) > 0:
            divergencias[campo] = round(min(1.0, spread / escala), 4)

    geo = escolhidos.get("geom", membros[0])
    tempo = escolhidos.get("observed_at", membros[0])
    observados = [m.observed_at for m in membros]

    return Canonico(
        cluster_key=chave,
        event_type=membros[0].event_type,
        lat=geo.lat,
        lon=geo.lon,
        observed_at=tempo.observed_at,
        lugar=escolhidos["lugar"].lugar if "lugar" in escolhidos else None,
        magnitude=escolhidos["magnitude"].magnitude if "magnitude" in escolhidos else None,
        profundidade_km=(
            escolhidos["profundidade_km"].profundidade_km
            if "profundidade_km" in escolhidos
            else None
        ),
        source_count=len({m.source_id for m in membros}),
        confianca=confianca(membros, divergencias),
        # 'reviewed' se qualquer fonte já revisou: é a informação mais forte
        # disponível sobre a solução.
        status=(
            "reviewed"
            if any(m.status == "reviewed" for m in membros)
            else "automatic"
        ),
        first_seen=min(observados),
        last_seen=max(observados),
        membros=list(membros),
        afirmacoes=afirmacoes,
        divergencias=divergencias,
    )
