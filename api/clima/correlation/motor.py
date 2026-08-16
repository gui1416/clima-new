"""O motor: blocking → cruzamento determinístico → score → cluster → síntese.

A ordem importa e não é arbitrária.

**Blocking primeiro** porque comparar todos contra todos é inviável e desnecessário:
o PostGIS resolve proximidade com índice GIST, e a janela temporal corta o resto.

**Cruzamento determinístico antes do probabilístico** porque boa parte do trabalho
é de graça e quase todo mundo ignora: as fontes já se referenciam mutuamente. O
USGS lista os identificadores de todas as redes contribuintes; o GDACS carrega
referência à origem; ReliefWeb traz número GLIDE. Onde há xref, o vínculo é
**certo** — gastar score probabilístico nele seria trocar certeza por estimativa.

**Reconstrução completa da janela**, não remendo incremental. Um cluster muda de
forma quando chega membro novo, e aplicar diffs em grafo é onde bugs de correlação
se esconderem. Reconstruir é O(candidatos) e idempotente por construção; o
append-only fica preservado porque só um *snapshot diferente* gera linha nova.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from clima.config import TENANT_SISTEMA
from clima.correlation.clustering import agrupar
from clima.correlation.features import (
    Parametros,
    Registro,
    explicar,
    extrair,
    score,
    veredito,
)
from clima.correlation.sintese import Canonico, sintetizar
from clima.db import sessao
from clima.logs import log

_log = log("correlacao")


@dataclass
class Relatorio:
    registros: int = 0
    candidatos: int = 0
    por_xref: int = 0
    unidos: int = 0
    incertos: int = 0
    rejeitados_por_diametro: int = 0
    eventos: int = 0
    eventos_multifonte: int = 0
    snapshots_novos: int = 0

    def como_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


# Chaves de `xrefs` que contêm identificador de EVENTO. Allowlist, não blocklist, e
# a diferença é de segurança: uma blocklist falha **aberto** — chave nova de uma fonte
# nova entra como identificador e funde eventos distintos em massa. Uma allowlist
# falha **fechado**: chave desconhecida é ignorada, custando recall e nunca inventando
# merge. Dado que falso merge esconde evento real, é o viés certo.
#
# O que NÃO entra, e por quê: `contribuintes` guarda siglas de rede do USGS ('nc',
# 'ci') e `agencia` guarda a agência do EMSC ('BMKG', 'AFAD'). São *quem reportou*,
# não *o que foi reportado* — tratá-los como identificador transformaria todo sismo da
# mesma rede num único evento.
CHAVES_IDENTIFICADOR = frozenset({"usgs", "emsc", "gdacs", "redes", "glide", "ids"})


def identificadores(r: Registro) -> set[str]:
    """Identificadores de evento que este registro declara.

    Interseção não vazia entre dois registros = mesmo evento, com certeza.
    """
    ids = {f"{r.source_id}:{r.source_event_id}"}
    for chave, valor in (r.xrefs or {}).items():
        if chave not in CHAVES_IDENTIFICADOR:
            continue
        if isinstance(valor, str):
            ids.add(valor)
        elif isinstance(valor, list):
            ids.update(str(v) for v in valor)
    return ids


async def _parametros(s: Any) -> dict[str, Parametros]:
    linhas = (await s.execute(text("SELECT * FROM correlation_params"))).all()
    return {
        r.event_type: Parametros(
            event_type=r.event_type,
            raio_m=r.raio_m,
            janela_seg=r.janela_seg,
            peso_espaco=r.peso_espaco,
            peso_tempo=r.peso_tempo,
            peso_metrica=r.peso_metrica,
            peso_toponimo=r.peso_toponimo,
            intercepto=r.intercepto,
            limiar_uniao=r.limiar_uniao,
            limiar_duvida=r.limiar_duvida,
            diametro_max_m=r.diametro_max_m,
            diametro_max_seg=r.diametro_max_seg,
        )
        for r in linhas
    }


SQL_REGISTROS = """
    SELECT id, source_id, source_event_id, event_type,
           ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon,
           observed_at, magnitude, profundidade_km, lugar, status, xrefs
    FROM v_registros_atuais
    WHERE observed_at > now() - make_interval(hours => :horas)
"""

# Blocking. O par sai ordenado (a<b) para casar com a PK de record_links, e o
# ST_DWithin usa o índice GIST — sem isso, é produto cartesiano.
SQL_CANDIDATOS = """
    WITH r AS (
      SELECT id, event_type, geom, observed_at
      FROM v_registros_atuais
      WHERE observed_at > now() - make_interval(hours => :horas)
    )
    SELECT a.id AS a_id, b.id AS b_id
    FROM r a
    JOIN correlation_params p ON p.event_type = a.event_type
    JOIN r b
      ON b.event_type = a.event_type
     AND a.id < b.id
     AND ST_DWithin(a.geom, b.geom, p.raio_m)
     AND abs(extract(epoch FROM a.observed_at - b.observed_at)) <= p.janela_seg
"""


async def correlacionar(horas: int = 48) -> Relatorio:
    rel = Relatorio()

    async with sessao() as s:
        params = await _parametros(s)
        registros = {
            r.id: Registro(
                id=r.id,
                source_id=r.source_id,
                source_event_id=r.source_event_id,
                event_type=r.event_type,
                lat=r.lat,
                lon=r.lon,
                observed_at=r.observed_at,
                magnitude=r.magnitude,
                profundidade_km=r.profundidade_km,
                lugar=r.lugar,
                status=r.status,
                xrefs=r.xrefs or {},
            )
            for r in (await s.execute(text(SQL_REGISTROS), {"horas": horas})).all()
        }
        candidatos = [
            (r.a_id, r.b_id)
            for r in (await s.execute(text(SQL_CANDIDATOS), {"horas": horas})).all()
        ]

    rel.registros = len(registros)
    rel.candidatos = len(candidatos)

    # ── decisão par a par ───────────────────────────────────────────────────
    vinculos: list[dict[str, Any]] = []
    pares_mesmo: list[tuple[int, int]] = []

    for a_id, b_id in candidatos:
        a, b = registros[a_id], registros[b_id]
        p = params.get(a.event_type)
        if p is None:
            # Tipo sem parâmetros calibrados: não adivinhar. Fica sem vínculo, e o
            # registro segue como evento próprio.
            continue

        if identificadores(a) & identificadores(b):
            vinculos.append(
                {
                    "a_id": a_id,
                    "b_id": b_id,
                    "metodo": "xref",
                    "veredito": "mesmo",
                    "score": 1.0,
                    "features": {
                        "identificador_comum": sorted(identificadores(a) & identificadores(b))
                    },
                }
            )
            pares_mesmo.append((a_id, b_id))
            rel.por_xref += 1
            continue

        f = extrair(a, b, p)
        sc = score(f, p)
        v = veredito(sc, p)
        vinculos.append(
            {
                "a_id": a_id,
                "b_id": b_id,
                "metodo": "probabilistico",
                "veredito": v,
                "score": round(sc, 5),
                "features": f.como_dict() | {"explicacao": explicar(f, p)},
            }
        )
        if v == "mesmo":
            pares_mesmo.append((a_id, b_id))
        elif v == "incerto":
            rel.incertos += 1

    # ── clusters, por tipo, com guarda de diâmetro ──────────────────────────
    clusters: list[list[Registro]] = []
    rebaixados: set[tuple[int, int]] = set()

    for tipo, p in params.items():
        do_tipo = {i: r for i, r in registros.items() if r.event_type == tipo}
        if not do_tipo:
            continue
        res = agrupar(do_tipo, [(a, b) for a, b in pares_mesmo if a in do_tipo], p)
        clusters.extend(res.clusters)
        rebaixados.update(res.rejeitados_por_diametro)

    # Registro de tipo sem parâmetro segue como evento isolado, para não desaparecer.
    cobertos = {r.id for c in clusters for r in c}
    clusters.extend([[r] for i, r in registros.items() if i not in cobertos])

    # Cluster reprovado no diâmetro: o par vira `incerto`, não `mesmo`. Fundir sem
    # confiança esconderia um evento real.
    for v in vinculos:
        if (v["a_id"], v["b_id"]) in rebaixados:
            v["veredito"] = "incerto"
            v["features"] = dict(v["features"]) | {"rebaixado": "diametro_do_cluster"}
            rel.incertos += 1
    rel.rejeitados_por_diametro = len(rebaixados)
    rel.unidos = sum(1 for v in vinculos if v["veredito"] == "mesmo")

    canonicos = [sintetizar(c) for c in clusters]
    rel.eventos = len(canonicos)
    rel.eventos_multifonte = sum(1 for c in canonicos if c.source_count > 1)

    async with sessao() as s:
        await _gravar_vinculos(s, vinculos)
        rel.snapshots_novos = await _gravar_canonicos(s, canonicos)

    _log.info("correlacao", **rel.como_dict())
    return rel


async def _gravar_vinculos(s: Any, vinculos: list[dict[str, Any]]) -> None:
    """Regrava os vínculos da janela. Decisão manual é preservada.

    ``metodo='manual'`` é veredito humano registrado; sobrescrevê-lo com o palpite
    do modelo apagaria o único dado de verdade-base que o sistema acumula.
    """
    for v in vinculos:
        await s.execute(
            text(
                """
                INSERT INTO record_links
                  (a_id, b_id, tenant_id, metodo, veredito, score, features)
                VALUES (:a, :b, :t, :m, :v, :s, CAST(:f AS jsonb))
                ON CONFLICT (a_id, b_id) DO UPDATE
                  SET metodo = EXCLUDED.metodo,
                      veredito = EXCLUDED.veredito,
                      score = EXCLUDED.score,
                      features = EXCLUDED.features,
                      decidido_em = now()
                  WHERE record_links.metodo <> 'manual'
                """
            ),
            {
                "a": v["a_id"],
                "b": v["b_id"],
                "t": TENANT_SISTEMA,
                "m": v["metodo"],
                "v": v["veredito"],
                "s": v["score"],
                "f": json.dumps(v["features"], default=str),
            },
        )


async def _resolver_evento(s: Any, c: Canonico) -> str:
    """Devolve o id do evento canônico deste cluster, criando ou reusando.

    **A identidade vem dos membros, não de uma chave derivada.** Se algum
    `source_record` do cluster já pertence a um evento canônico, esse evento é o
    mesmo — ele apenas ganhou (ou perdeu) membros. Reconstruir a identidade a partir
    de rótulo era o defeito: a chave mudava quando entrava membro de fonte
    alfabeticamente menor, criando evento novo e orfanando snapshots.

    Quando o cluster cobre **vários** eventos canônicos já existentes, é uma fusão:
    duas coisas rastreadas em separado passaram a ser reconhecidas como a mesma. O
    mais antigo sobrevive; os outros ficam no banco apontando para ele via
    `fundido_em`, e saem do estado atual. Apagá-los perderia histórico.
    """
    ids = [m.id for m in c.membros]
    existentes = list(
        (
            await s.execute(
                text(
                    """
                    SELECT DISTINCT e.id, e.first_seen
                    FROM canonical_event_membros m
                    JOIN canonical_events e ON e.id = m.canonical_event_id
                    WHERE m.source_record_id = ANY(:ids) AND e.fundido_em IS NULL
                    ORDER BY e.first_seen, e.id
                    """
                ),
                {"ids": ids},
            )
        ).all()
    )

    if not existentes:
        return str(
            (
                await s.execute(
                    text(
                        """
                        INSERT INTO canonical_events
                          (tenant_id, event_type, first_seen, last_seen, cluster_key)
                        VALUES (:t, :tipo, :ini, :fim, :chave)
                        RETURNING id
                        """
                    ),
                    {
                        "t": TENANT_SISTEMA,
                        "tipo": c.event_type,
                        "ini": c.first_seen,
                        "fim": c.last_seen,
                        "chave": c.cluster_key,
                    },
                )
            ).scalar_one()
        )

    sobrevivente = existentes[0].id
    for absorvido in existentes[1:]:
        # Membros migram para o sobrevivente; o evento absorvido fica com seu
        # histórico intacto e marcado.
        await s.execute(
            text("DELETE FROM canonical_event_membros WHERE canonical_event_id = :e"),
            {"e": absorvido.id},
        )
        await s.execute(
            text("UPDATE canonical_events SET fundido_em = :s WHERE id = :e"),
            {"s": sobrevivente, "e": absorvido.id},
        )
        _log.info("eventos_fundidos", sobrevivente=str(sobrevivente), absorvido=str(absorvido.id))

    await s.execute(
        text(
            """
            UPDATE canonical_events
               SET first_seen = least(first_seen, :ini),
                   last_seen  = greatest(last_seen, :fim),
                   cluster_key = :chave
             WHERE id = :e
            """
        ),
        {"ini": c.first_seen, "fim": c.last_seen, "chave": c.cluster_key, "e": sobrevivente},
    )
    return str(sobrevivente)


async def _gravar_canonicos(s: Any, canonicos: list[Canonico]) -> int:
    novos = 0
    for c in canonicos:
        evento_id = await _resolver_evento(s, c)

        # Snapshot novo só quando o estado mudou de fato: é o que mantém o
        # append-only informativo em vez de uma linha por execução do worker.
        atual = (
            await s.execute(
                text(
                    """
                    SELECT seq, magnitude, source_count, status,
                           ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
                    FROM canonical_event_snapshots
                    WHERE canonical_event_id = :e
                    ORDER BY seq DESC LIMIT 1
                    """
                ),
                {"e": evento_id},
            )
        ).first()

        mudou = atual is None or (
            (atual.magnitude, atual.source_count, atual.status)
            != (c.magnitude, c.source_count, c.status)
            or abs(atual.lat - c.lat) > 1e-5
            or abs(atual.lon - c.lon) > 1e-5
        )

        if mudou:
            motivo = "primeira_observacao"
            if atual is not None:
                if atual.source_count != c.source_count:
                    motivo = "nova_fonte"
                elif atual.magnitude != c.magnitude:
                    motivo = "magnitude_revisada"
                elif atual.status != c.status:
                    motivo = "revisado_por_analista"
                else:
                    motivo = "epicentro_revisado"
            await s.execute(
                text(
                    """
                    INSERT INTO canonical_event_snapshots
                      (canonical_event_id, seq, geom, observed_at, lugar, magnitude,
                       profundidade_km, metrics, source_count, confianca, status, motivo_mudanca)
                    VALUES (:e, coalesce((SELECT max(seq) + 1 FROM canonical_event_snapshots
                                            WHERE canonical_event_id = :e), 1),
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                            :obs, :lugar, :mag, :prof, CAST(:met AS jsonb),
                            :n, :conf, :st, :motivo)
                    """
                ),
                {
                    "e": evento_id,
                    "lon": c.lon,
                    "lat": c.lat,
                    "obs": c.observed_at,
                    "lugar": c.lugar,
                    "mag": c.magnitude,
                    "prof": c.profundidade_km,
                    "met": json.dumps({"divergencias": c.divergencias}),
                    "n": c.source_count,
                    "conf": c.confianca,
                    "st": c.status,
                    "motivo": motivo,
                },
            )
            novos += 1

        # Membros e afirmações são conjuntos derivados, não observações: regravar é
        # correto, e é o que mantém o resultado idempotente quando o cluster muda.
        await s.execute(
            text("DELETE FROM canonical_event_membros WHERE canonical_event_id = :e"),
            {"e": evento_id},
        )
        for m in c.membros:
            await s.execute(
                text(
                    "INSERT INTO canonical_event_membros "
                    "(canonical_event_id, source_record_id, source_id) VALUES (:e, :r, :f) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"e": evento_id, "r": m.id, "f": m.source_id},
            )

        await s.execute(
            text("DELETE FROM event_field_claims WHERE canonical_event_id = :e"),
            {"e": evento_id},
        )
        for af in c.afirmacoes:
            await s.execute(
                text(
                    """
                    INSERT INTO event_field_claims
                      (canonical_event_id, campo, source_id, valor, source_record_id, vencedor)
                    VALUES (:e, :campo, :fonte, CAST(:valor AS jsonb), :reg, :venceu)
                    ON CONFLICT (canonical_event_id, campo, source_id) DO UPDATE
                      SET valor = EXCLUDED.valor,
                          source_record_id = EXCLUDED.source_record_id,
                          vencedor = EXCLUDED.vencedor
                    """
                ),
                {
                    "e": evento_id,
                    "campo": af.campo,
                    "fonte": af.source_id,
                    "valor": json.dumps(af.valor, default=str),
                    "reg": af.source_record_id,
                    "venceu": af.vencedor,
                },
            )

    return novos
