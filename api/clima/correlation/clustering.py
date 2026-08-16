"""Pares → clusters, com guarda contra encadeamento.

O risco central: A~B, B~C, mas A e C são claramente distintos, e a transitividade
cega funde os três. Union-find puro faz exatamente isso.

A guarda mede o **diâmetro** do cluster formado — a maior distância espaço-temporal
entre quaisquer dois membros — e compara com o limite do tipo. Cluster que estoura
não é fundido em silêncio: volta a ser registros separados e os pares que o
formariam ficam marcados `incerto`, para revisão humana.

Isso implementa "falso merge é pior que falso split" no nível estrutural, e não
como intenção.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from clima.correlation.features import Parametros, Registro, distancia_m


class UnionFind:
    def __init__(self) -> None:
        self._pai: dict[int, int] = {}

    def achar(self, x: int) -> int:
        self._pai.setdefault(x, x)
        raiz = x
        while self._pai[raiz] != raiz:
            raiz = self._pai[raiz]
        # Compressão de caminho: mantém as consultas seguintes rasas.
        while self._pai[x] != raiz:
            self._pai[x], x = raiz, self._pai[x]
        return raiz

    def unir(self, a: int, b: int) -> None:
        ra, rb = self.achar(a), self.achar(b)
        if ra != rb:
            self._pai[rb] = ra

    def grupos(self) -> dict[int, list[int]]:
        saida: dict[int, list[int]] = {}
        for x in list(self._pai):
            saida.setdefault(self.achar(x), []).append(x)
        for membros in saida.values():
            membros.sort()
        return saida


@dataclass(frozen=True, slots=True)
class Diametro:
    metros: float
    segundos: float

    def cabe(self, p: Parametros) -> bool:
        return self.metros <= p.diametro_max_m and self.segundos <= p.diametro_max_seg


def diametro(membros: list[Registro]) -> Diametro:
    """Maior distância e maior intervalo entre quaisquer dois membros.

    O(n²), e isso é aceitável: clusters de correlação têm poucos membros — uma
    fonte por rede, não milhares. Se algum dia tiverem, o problema é outro.
    """
    max_m = 0.0
    max_s = 0.0
    for i, a in enumerate(membros):
        for b in membros[i + 1 :]:
            max_m = max(max_m, distancia_m(a.lat, a.lon, b.lat, b.lon))
            max_s = max(max_s, abs((a.observed_at - b.observed_at).total_seconds()))
    return Diametro(max_m, max_s)


@dataclass
class Resultado:
    """Clusters aceitos e os pares que foram rebaixados para revisão."""

    clusters: list[list[Registro]] = field(default_factory=list)
    rejeitados_por_diametro: list[tuple[int, int]] = field(default_factory=list)


def agrupar(
    registros: dict[int, Registro],
    pares_mesmo: list[tuple[int, int]],
    p: Parametros,
) -> Resultado:
    """Une os pares aprovados e valida o diâmetro de cada cluster formado.

    Quando um cluster estoura, ele é **desfeito por completo** em vez de podado por
    heurística. Escolher qual aresta cortar sem evidência seria inventar uma decisão
    que o dado não sustenta; devolver os membros como registros isolados e mandar os
    pares para revisão é a resposta honesta.
    """
    uf = UnionFind()
    for a in registros:
        uf.achar(a)
    for a, b in pares_mesmo:
        uf.unir(a, b)

    res = Resultado()
    for membros_ids in uf.grupos().values():
        membros = [registros[i] for i in membros_ids if i in registros]
        if len(membros) == 1:
            res.clusters.append(membros)
            continue

        if diametro(membros).cabe(p):
            res.clusters.append(membros)
        else:
            conjunto = set(membros_ids)
            res.rejeitados_por_diametro.extend(
                (a, b) for a, b in pares_mesmo if a in conjunto and b in conjunto
            )
            res.clusters.extend([[m] for m in membros])

    res.clusters.sort(key=lambda c: c[0].id)
    return res
