"""Fila de revisão humana do motor de correlação."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from clima.api.esquemas import DecisaoRevisao, ItemRevisao, PaginaRevisao, RevisaoRegistrada
from clima.config import config
from clima.correlation import correlacionar
from clima.db import sessao

router = APIRouter(prefix="/revisoes", tags=["revisão"])


def _autorizar(chave: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    esperada = config().admin_api_key
    if not esperada or not chave or not secrets.compare_digest(chave, esperada):
        raise HTTPException(401, "credencial administrativa inválida")


@router.get("", response_model=PaginaRevisao)
async def listar_revisoes(
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> PaginaRevisao:
    _autorizar(x_api_key)
    async with sessao() as s:
        total = (await s.execute(text("SELECT count(*) FROM v_revisao_pendente"))).scalar_one()
        linhas = (
            await s.execute(
                text("SELECT * FROM v_revisao_pendente LIMIT :limite OFFSET :offset"),
                {"limite": limite, "offset": offset},
            )
        ).all()
    return PaginaRevisao(total=total, itens=[ItemRevisao(**dict(r._mapping)) for r in linhas])


@router.put("/{a_id}/{b_id}", response_model=RevisaoRegistrada)
async def decidir_revisao(
    a_id: int,
    b_id: int,
    decisao: DecisaoRevisao,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> RevisaoRegistrada:
    _autorizar(x_api_key)
    if a_id >= b_id:
        raise HTTPException(422, "o par deve estar na ordem a_id < b_id")
    async with sessao() as s:
        linha = (
            await s.execute(
                text(
                    """
                    UPDATE record_links
                    SET metodo = 'manual', veredito = :veredito, decidido_por = :revisor,
                        decidido_em = now(),
                        features = features || jsonb_build_object(
                          'justificativa_manual', CAST(:justificativa AS text))
                    WHERE a_id = :a AND b_id = :b AND veredito = 'incerto'
                    RETURNING a_id, b_id, veredito, decidido_por, decidido_em
                    """
                ),
                {
                    "a": a_id,
                    "b": b_id,
                    "veredito": decisao.veredito,
                    "revisor": decisao.revisor,
                    "justificativa": decisao.justificativa,
                },
            )
        ).first()
        if linha is None:
            raise HTTPException(404, "revisão pendente não encontrada")

    # A decisão manual é preservada pelo motor e passa a reger os clusters.
    await correlacionar()
    return RevisaoRegistrada(
        a_id=linha.a_id,
        b_id=linha.b_id,
        veredito=linha.veredito,
        revisor=linha.decidido_por,
        decidido_em=linha.decidido_em,
    )


__all__ = ["router"]
