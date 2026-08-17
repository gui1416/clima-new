"""Leitura de eventos, sobre ``v_eventos_canonicos``.

"Evento" aqui é o resultado do motor de correlação: um fenômeno do mundo real, com
as fontes que o confirmam e a divergência entre elas preservada. Até a Fase 2 esta
rota servia `v_registros_atuais` — registro de fonte —, e o cliente precisava supor
consolidação que não havia.

``deduplicado: true`` significa que houve consolidação, **não** que o portão G2 foi
atendido. Enquanto a sobreposição entre USGS e EMSC for rara (só na faixa global de
M ≳ 4,5), a maioria dos eventos terá uma fonte só, e o `aviso` diz isso.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from clima.api.esquemas import (
    CampoDivergente,
    Estatisticas,
    EventoDetalhe,
    EventoResumo,
    Pagina,
    Procedencia,
    ValorDeFonte,
)
from clima.db import sessao
from clima.dominio import Redistribuicao

router = APIRouter(tags=["eventos"])

# O feed do USGS inclui microssismos (M < 1). Para monitoramento de desastre isso é
# ruído. O corte é de APRESENTAÇÃO, não de ingestão — tudo continua gravado, e o
# cliente pode baixar o piso até 0.
MAGNITUDE_MINIMA_PADRAO = 2.5

ROTULO_CAMPO = {
    "magnitude": "magnitude",
    "profundidade_km": "profundidade",
    "geom": "epicentro",
    "observed_at": "horário de origem",
    "lugar": "localidade",
}


def _titulo(lugar: str | None, magnitude: float | None, tipo: str) -> str:
    """Rótulo em pt-BR, com arredondamento half-up explícito.

    O `format` do Python é half-even, o `Intl` do navegador é half-up: M 2,65 sairia
    "2,6" aqui e "2,7" na tabela. Num produto cuja tese é "as fontes discordam entre
    si", discordar de si mesmo é o pior detalhe possível.
    """
    nome = {"earthquake": "Sismo", "quarry blast": "Detonação"}.get(tipo, tipo.capitalize())
    if magnitude is None:
        return f"{nome} — {lugar or 'local não informado'}"
    arredondado = Decimal(str(magnitude)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{nome} M {arredondado}".replace(".", ",")


def _resumo(r: Any) -> EventoResumo:
    return EventoResumo(
        id=str(r.id),
        titulo=_titulo(r.lugar, r.magnitude, r.event_type),
        tipo=r.event_type,
        lugar=r.lugar,
        lat=r.lat,
        lon=r.lon,
        ocorrido_em=r.observed_at,
        atualizado_em=r.atualizado_em,
        severidade=r.severidade,
        magnitude=r.magnitude,
        metrica_rotulo="magnitude",
        profundidade_km=r.profundidade_km,
        fontes_confirmando=r.source_count,
        fontes=list(r.fontes or []),
        confianca=r.confianca,
        snapshots=r.snapshots,
        status=r.status,
    )


SELECT_BASE = """
    SELECT v.*,
           ST_Y(v.geom::geometry) AS lat,
           ST_X(v.geom::geometry) AS lon
    FROM v_eventos_canonicos v
    WHERE v.observed_at > now() - make_interval(hours => :horas)
      AND (v.magnitude IS NULL OR v.magnitude >= :mag_min)
      AND (:severidade = '' OR v.severidade = :severidade)
      AND (:fontes_min = 0 OR v.source_count >= :fontes_min)
      AND (:bbox = '' OR ST_Intersects(
             v.geom,
             ST_MakeEnvelope(
               split_part(:bbox, ',', 1)::float, split_part(:bbox, ',', 2)::float,
               split_part(:bbox, ',', 3)::float, split_part(:bbox, ',', 4)::float,
               4326)::geography))
"""


def _aviso(total: int, multifonte: int) -> str:
    if multifonte:
        return (
            f"{multifonte} de {total} eventos são confirmados por mais de uma fonte. "
            "Os demais têm fonte única — a sobreposição entre USGS e EMSC ocorre "
            "sobretudo acima de M 4,5."
        )
    return (
        "Nenhum evento nesta janela tem mais de uma fonte. O motor de correlação está "
        "ativo; a sobreposição entre USGS e EMSC ocorre sobretudo acima de M 4,5 e é "
        "pouco frequente por hora."
    )


@router.get("/eventos", response_model=Pagina)
async def listar(
    horas: Annotated[int, Query(ge=1, le=24 * 30, description="Janela de tempo")] = 24,
    magnitude_minima: Annotated[float, Query(ge=0, le=10)] = MAGNITUDE_MINIMA_PADRAO,
    severidade: Annotated[str, Query(pattern="^(critical|high|moderate|)$")] = "",
    fontes_minimas: Annotated[
        int, Query(ge=0, le=10, description="Só eventos com pelo menos N fontes")
    ] = 0,
    bbox: Annotated[str, Query(description="oeste,sul,leste,norte")] = "",
    limite: Annotated[int, Query(ge=1, le=1000)] = 300,
) -> Pagina:
    if bbox:
        partes = bbox.split(",")
        if len(partes) != 4:
            raise HTTPException(422, "bbox precisa de quatro números: oeste,sul,leste,norte")
        try:
            [float(p) for p in partes]
        except ValueError:
            raise HTTPException(422, "bbox com valor não numérico") from None

    params = {
        "horas": horas,
        "mag_min": magnitude_minima,
        "severidade": severidade,
        "fontes_min": fontes_minimas,
        "bbox": bbox,
    }
    async with sessao() as s:
        agg = (
            await s.execute(
                text(
                    f"SELECT count(*) AS total, "
                    f"count(*) FILTER (WHERE source_count > 1) AS multi "
                    f"FROM ({SELECT_BASE}) q"
                ),
                params,
            )
        ).one()
        linhas = (
            await s.execute(
                text(f"{SELECT_BASE} ORDER BY v.observed_at DESC LIMIT :limite"),
                params | {"limite": limite},
            )
        ).all()

    return Pagina(
        total=agg.total,
        itens=[_resumo(r) for r in linhas],
        deduplicado=True,
        aviso=_aviso(agg.total, agg.multi),
    )


@router.get("/eventos/{evento_id}", response_model=EventoDetalhe)
async def detalhar(evento_id: str) -> EventoDetalhe:
    async with sessao() as s:
        linha = (
            await s.execute(
                text(
                    """
                    SELECT v.*, ST_Y(v.geom::geometry) AS lat, ST_X(v.geom::geometry) AS lon
                    FROM v_eventos_canonicos v
                    WHERE v.id = CAST(:i AS uuid)
                    """
                ),
                {"i": evento_id},
            )
        ).first()
        if linha is None:
            raise HTTPException(404, "evento não encontrado")

        membros = (
            await s.execute(
                text(
                    """
                    SELECT r.source_id, s.nome, r.source_event_id, r.observed_at,
                           r.source_updated_at, r.status, s.redistribuicao,
                           s.atribuicao_exigida, r.metrics
                    FROM canonical_event_membros m
                    JOIN source_records r ON r.id = m.source_record_id
                    JOIN sources s ON s.id = r.source_id
                    WHERE m.canonical_event_id = CAST(:i AS uuid)
                    ORDER BY r.source_id
                    """
                ),
                {"i": evento_id},
            )
        ).all()

        claims = (
            await s.execute(
                text(
                    """
                    SELECT c.campo, c.source_id, c.valor, c.vencedor, s.redistribuicao
                    FROM event_field_claims c
                    JOIN sources s ON s.id = c.source_id
                    WHERE c.canonical_event_id = CAST(:i AS uuid)
                    ORDER BY c.campo, c.source_id
                    """
                ),
                {"i": evento_id},
            )
        ).all()

    # A trava de licença, aplicada na serialização: fonte 'interna' entra na
    # contagem e na confiança, e o conteúdo dela não sai. Portão G4.
    restritas = {
        m.source_id for m in membros if m.redistribuicao == Redistribuicao.INTERNA
    }

    por_campo: dict[str, list[ValorDeFonte]] = {}
    for c in claims:
        restrito = c.redistribuicao == Redistribuicao.INTERNA
        por_campo.setdefault(c.campo, []).append(
            ValorDeFonte(
                fonte=c.source_id,
                valor=None if restrito else c.valor,
                vencedor=c.vencedor,
                conteudo_restrito=restrito,
            )
        )

    campos = [
        CampoDivergente(
            campo=ROTULO_CAMPO.get(campo, campo),
            valores=valores,
            # Divergente quando as fontes não afirmam o mesmo valor. Restrito conta
            # como desconhecido, não como concordância.
            divergente=len({str(v.valor) for v in valores if not v.conteudo_restrito}) > 1,
        )
        for campo, valores in sorted(por_campo.items())
    ]

    metricas: dict[str, Any] = {}
    for m in membros:
        if m.source_id not in restritas:
            metricas[m.source_id] = dict(m.metrics or {})

    return EventoDetalhe(
        **_resumo(linha).model_dump(),
        metricas=metricas,
        procedencia=[
            Procedencia(
                fonte=m.source_id,
                nome=m.nome,
                source_event_id=m.source_event_id,
                observado_em=m.observed_at,
                revisado_em=m.source_updated_at,
                status=m.status,
                atribuicao=m.atribuicao_exigida,
                conteudo_restrito=m.source_id in restritas,
            )
            for m in membros
        ],
        campos=campos,
    )


@router.get("/estatisticas", response_model=Estatisticas)
async def estatisticas(
    horas: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
    magnitude_minima: Annotated[float, Query(ge=0, le=10)] = MAGNITUDE_MINIMA_PADRAO,
) -> Estatisticas:
    params: dict[str, Any] = {
        "horas": horas,
        "mag_min": magnitude_minima,
        "severidade": "",
        "fontes_min": 0,
        "bbox": "",
    }
    async with sessao() as s:
        agg = (
            await s.execute(
                text(
                    f"""
                    WITH q AS ({SELECT_BASE})
                    SELECT count(*) AS total, max(magnitude) AS mag_max,
                           max(observed_at) AS ultimo,
                           count(*) FILTER (WHERE source_count > 1) AS multi
                    FROM q
                    """
                ),
                params,
            )
        ).one()
        por_sev = dict(
            (
                await s.execute(
                    text(f"WITH q AS ({SELECT_BASE}) SELECT severidade, count(*) FROM q GROUP BY 1"),
                    params,
                )
            ).all()
        )
        por_status = dict(
            (
                await s.execute(
                    text(f"WITH q AS ({SELECT_BASE}) SELECT status, count(*) FROM q GROUP BY 1"),
                    params,
                )
            ).all()
        )
        ativas = (await s.execute(text("SELECT count(*) FROM sources WHERE ativa"))).scalar_one()

    return Estatisticas(
        eventos_total=agg.total,
        por_severidade=por_sev,
        por_status=por_status,
        magnitude_maxima=agg.mag_max,
        ultimo_evento_em=agg.ultimo,
        janela_horas=horas,
        fontes_ativas=ativas,
        eventos_multifonte=agg.multi,
        deduplicado=True,
    )


__all__ = ["router"]
