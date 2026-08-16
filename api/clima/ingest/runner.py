"""O coletor. É o serviço mais importante da Fase 0.

Enquanto isto não estiver rodando em produção, cada minuto é um minuto de
histórico que não existirá nunca. Nada mais do projeto tem essa propriedade.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from clima.config import TENANT_SISTEMA, config
from clima.connectors import Validadores, conector
from clima.db import sessao
from clima.dominio import ResultadoColeta
from clima.logs import log
from clima.models import ColetaRun, CorpoPayload, Fonte, RawPayload

_log = log("ingest")


async def coletar_fonte(source_id: str) -> ResultadoColeta:
    """Uma coleta completa: abre o run, busca, grava o cru, fecha o run."""
    cfg = config()

    # Transação 1 — abre o run antes de tocar a rede. Se o processo morrer no
    # meio da requisição, a tentativa fica registrada e a varredura de lacunas
    # enxerga o buraco em vez de o minuto simplesmente não existir.
    async with sessao() as s:
        anteriores = await _ultimos_validadores(s, source_id)
        run = ColetaRun(tenant_id=TENANT_SISTEMA, source_id=source_id)
        s.add(run)
        await s.flush()
        run_id = run.id

    # A requisição roda FORA de transação. Segurar uma transação Postgres aberta
    # durante uma chamada a terceiro é como se esgota o pool de conexões.
    try:
        async with httpx.AsyncClient(
            timeout=cfg.http_timeout_seg,
            headers={"User-Agent": cfg.user_agent},
            follow_redirects=True,
        ) as cliente:
            resposta = await conector(source_id).coletar(cliente, anteriores)
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira run com erro
        await _fechar_com_erro(run_id, exc)
        _log.error("coleta_falhou", source_id=source_id, run_id=run_id, erro=str(exc))
        # Sem re-raise de propósito: o próximo tick vem em segundos e o feed
        # se sobrepõe por uma hora inteira. Retry imediato não recupera nada
        # que a próxima coleta já não cubra, e só castiga a fonte.
        return ResultadoColeta.ERRO

    if resposta.nao_modificado:
        async with sessao() as s:
            await s.execute(
                update(ColetaRun)
                .where(ColetaRun.id == run_id)
                .values(
                    finished_at=func.now(),
                    url=resposta.url,
                    http_status=resposta.http_status,
                    resultado=ResultadoColeta.NAO_MODIFICADO,
                )
            )
        _log.info("coleta_nao_modificada", source_id=source_id, run_id=run_id)
        return ResultadoColeta.NAO_MODIFICADO

    corpo = resposta.body or b""
    sha = hashlib.sha256(corpo).digest()

    async with sessao() as s:
        # Corpo endereçado por conteúdo: corpo repetido não ocupa espaço de novo.
        await s.execute(
            pg_insert(CorpoPayload)
            .values(
                sha256=sha,
                body=corpo,
                bytes_total=len(corpo),
                content_type=resposta.content_type,
            )
            .on_conflict_do_nothing(index_elements=["sha256"])
        )
        # A coleta em si é sempre registrada, mesmo com corpo repetido — é o que
        # prova continuidade de coleta.
        s.add(
            RawPayload(
                tenant_id=TENANT_SISTEMA,
                source_id=source_id,
                ingest_run_id=run_id,
                url=resposta.url,
                http_status=resposta.http_status,
                headers=dict(resposta.headers),
                body_sha256=sha,
            )
        )
        await s.execute(
            update(ColetaRun)
            .where(ColetaRun.id == run_id)
            .values(
                finished_at=func.now(),
                url=resposta.url,
                http_status=resposta.http_status,
                resultado=ResultadoColeta.OK,
                bytes_recebidos=len(corpo),
                body_sha256=sha,
                etag=resposta.validadores.etag,
                last_modified=resposta.validadores.last_modified,
            )
        )

    _log.info(
        "coleta_ok",
        source_id=source_id,
        run_id=run_id,
        bytes=len(corpo),
        sha256=sha.hex()[:12],
    )
    return ResultadoColeta.OK


async def coletar_ativas() -> dict[str, str]:
    """Coleta todas as fontes marcadas ativas e com conector implementado."""
    async with sessao() as s:
        ids = list((await s.execute(select(Fonte.id).where(Fonte.ativa.is_(True)))).scalars())

    resultados: dict[str, str] = {}
    for source_id in ids:
        try:
            resultados[source_id] = (await coletar_fonte(source_id)).value
        except LookupError as exc:
            # Fonte ativa no banco sem conector no código: erro de configuração,
            # não de rede. Registra e segue com as outras.
            _log.warning("fonte_sem_conector", source_id=source_id, erro=str(exc))
            resultados[source_id] = "sem_conector"
    return resultados


async def _ultimos_validadores(s, source_id: str) -> Validadores:  # noqa: ANN001
    """ETag/Last-Modified da última coleta que trouxe corpo.

    Filtra por ``ok`` de propósito: uma resposta 304 não carrega necessariamente
    os validadores, e herdar NULL dela desligaria a requisição condicional para
    sempre.
    """
    linha = (
        await s.execute(
            select(ColetaRun.etag, ColetaRun.last_modified)
            .where(
                ColetaRun.source_id == source_id,
                ColetaRun.resultado == ResultadoColeta.OK,
            )
            .order_by(ColetaRun.started_at.desc())
            .limit(1)
        )
    ).first()
    if linha is None:
        return Validadores()
    return Validadores(etag=linha.etag, last_modified=linha.last_modified)


async def _fechar_com_erro(run_id: int, exc: Exception) -> None:
    async with sessao() as s:
        await s.execute(
            update(ColetaRun)
            .where(ColetaRun.id == run_id)
            .values(
                finished_at=datetime.now(UTC),
                resultado=ResultadoColeta.ERRO,
                erro=f"{type(exc).__name__}: {exc}"[:2000],
            )
        )
