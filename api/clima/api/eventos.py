"""Leitura de eventos, sobre ``v_registros_atuais``.

Enquanto o motor de correlação não existe (Fase 2), "evento" aqui é *um registro
de uma fonte*. A API diz isso em toda resposta com ``deduplicado: false`` — em vez
de deixar o cliente supor consolidação que não houve.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from clima.api.esquemas import (
    Estatisticas,
    EventoDetalhe,
    EventoResumo,
    Pagina,
    Procedencia,
)
from clima.db import sessao
from clima.dominio import Redistribuicao

router = APIRouter(tags=["eventos"])

AVISO_SEM_DEDUP = (
    "Sem deduplicação entre fontes: cada item é o registro de uma única fonte. "
    "O motor de correlação é a Fase 2."
)

# O feed all_hour do USGS inclui microssismos (M < 1). Para um produto de
# monitoramento de desastre isso é ruído: uma tarde na Califórnia enche o mapa.
# O corte é de APRESENTAÇÃO, não de ingestão — tudo continua gravado, e o cliente
# pode baixar o piso até 0.
MAGNITUDE_MINIMA_PADRAO = 2.5


def _titulo(lugar: str | None, magnitude: float | None, tipo: str) -> str:
    """Rótulo em pt-BR. Vírgula decimal, como o resto da interface.

    Arredondamento **half-up** explícito, não o `format` do Python. O padrão de
    ponto flutuante é half-even, então M 2,65 sairia "2,6" aqui e "2,7" no
    `Intl.NumberFormat` do navegador — o mesmo número aparecendo de dois jeitos na
    mesma linha da tabela. Num produto cuja tese é "as fontes discordam entre si",
    discordar de si mesmo é o pior detalhe possível.
    """
    nome = {"earthquake": "Sismo", "quarry blast": "Detonação"}.get(tipo, tipo.capitalize())
    if magnitude is None:
        return f"{nome} — {lugar or 'local não informado'}"
    arredondado = Decimal(str(magnitude)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{nome} M {arredondado}".replace(".", ",")


def _procedencia(r: Any) -> Procedencia:
    restrito = r.redistribuicao == Redistribuicao.INTERNA
    return Procedencia(
        fonte=r.source_id,
        nome=r.fonte_nome,
        source_event_id=r.source_event_id,
        observado_em=r.observed_at,
        revisado_em=r.source_updated_at,
        revisoes=r.revisoes,
        status=r.status,
        # A trava de licença: fonte 'interna' entra na contagem e na confiança,
        # mas o conteúdo dela não sai numa resposta. Portão G4 do plano.
        magnitude=None if restrito else r.magnitude,
        profundidade_km=None if restrito else r.profundidade_km,
        lugar=None if restrito else r.lugar,
        atribuicao=r.atribuicao_exigida,
        conteudo_restrito=restrito,
    )


def _resumo(r: Any) -> EventoResumo:
    return EventoResumo(
        id=f"{r.source_id}:{r.source_event_id}",
        titulo=_titulo(r.lugar, r.magnitude, r.event_type),
        tipo=r.event_type,
        lugar=r.lugar,
        lat=r.lat,
        lon=r.lon,
        ocorrido_em=r.observed_at,
        atualizado_em=r.source_updated_at,
        severidade=r.severidade,
        magnitude=r.magnitude,
        metrica_rotulo="magnitude",
        profundidade_km=r.profundidade_km,
        fontes_confirmando=1,
        revisoes=r.revisoes,
        status=r.status,
    )


SELECT_BASE = """
    SELECT v.*, s.nome AS fonte_nome,
           ST_Y(v.geom::geometry) AS lat,
           ST_X(v.geom::geometry) AS lon
    FROM v_registros_atuais v
    JOIN sources s ON s.id = v.source_id
    WHERE v.observed_at > now() - make_interval(hours => :horas)
      AND (v.magnitude IS NULL OR v.magnitude >= :mag_min)
      AND (:severidade = '' OR v.severidade = :severidade)
      AND (:bbox = '' OR ST_Intersects(
             v.geom,
             ST_MakeEnvelope(
               split_part(:bbox, ',', 1)::float, split_part(:bbox, ',', 2)::float,
               split_part(:bbox, ',', 3)::float, split_part(:bbox, ',', 4)::float,
               4326)::geography))
"""


@router.get("/eventos", response_model=Pagina)
async def listar(
    horas: Annotated[int, Query(ge=1, le=24 * 30, description="Janela de tempo")] = 24,
    magnitude_minima: Annotated[float, Query(ge=0, le=10)] = MAGNITUDE_MINIMA_PADRAO,
    severidade: Annotated[str, Query(pattern="^(critical|high|moderate|)$")] = "",
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
        "bbox": bbox,
    }
    async with sessao() as s:
        total = (
            await s.execute(text(f"SELECT count(*) FROM ({SELECT_BASE}) q"), params)
        ).scalar_one()
        linhas = (
            await s.execute(
                text(f"{SELECT_BASE} ORDER BY v.observed_at DESC LIMIT :limite"),
                params | {"limite": limite},
            )
        ).all()

    return Pagina(
        total=total,
        itens=[_resumo(r) for r in linhas],
        deduplicado=False,
        aviso=AVISO_SEM_DEDUP,
    )


@router.get("/eventos/{fonte}:{evento_id}", response_model=EventoDetalhe)
async def detalhar(fonte: str, evento_id: str) -> EventoDetalhe:
    async with sessao() as s:
        linha = (
            await s.execute(
                text(
                    """
                    SELECT v.*, s.nome AS fonte_nome,
                           ST_Y(v.geom::geometry) AS lat,
                           ST_X(v.geom::geometry) AS lon
                    FROM v_registros_atuais v
                    JOIN sources s ON s.id = v.source_id
                    WHERE v.source_id = :fonte AND v.source_event_id = :evento
                    """
                ),
                {"fonte": fonte, "evento": evento_id},
            )
        ).first()

    if linha is None:
        raise HTTPException(404, "evento não encontrado")

    restrito = linha.redistribuicao == Redistribuicao.INTERNA
    base = _resumo(linha)
    return EventoDetalhe(
        **base.model_dump(),
        metricas={} if restrito else dict(linha.metrics or {}),
        xrefs=dict(linha.xrefs or {}),
        # Uma fonte hoje. A lista existe com a forma final para que a interface do
        # painel de procedência não precise ser reescrita na Fase 2.
        procedencia=[_procedencia(linha)],
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
        "bbox": "",
    }
    async with sessao() as s:
        agg = (
            await s.execute(
                text(
                    f"""
                    WITH q AS ({SELECT_BASE})
                    SELECT count(*) AS total,
                           max(magnitude) AS mag_max,
                           max(observed_at) AS ultimo
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
        ativas = (
            await s.execute(text("SELECT count(*) FROM sources WHERE ativa"))
        ).scalar_one()

    return Estatisticas(
        eventos_total=agg.total,
        por_severidade=por_sev,
        por_status=por_status,
        magnitude_maxima=agg.mag_max,
        ultimo_evento_em=agg.ultimo,
        janela_horas=horas,
        fontes_ativas=ativas,
        deduplicado=False,
    )


__all__ = ["router"]
