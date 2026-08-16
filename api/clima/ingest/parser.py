"""Análise: ``payload_bodies`` → ``source_records``.

Nunca toca a rede. Lê o corpo já gravado, o que dá três coisas de graça:

* bug de parser é replay, não perda de dado;
* o parser é função pura, testável contra payload real armazenado;
* reprocessar o histórico inteiro é apagar linhas de ``parse_runs``.
"""

from __future__ import annotations

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from clima.config import TENANT_SISTEMA
from clima.connectors import conector
from clima.db import sessao
from clima.logs import log
from clima.models import ParseRun, SourceRecord

_log = log("parser")

# Teto por rodada. O worker roda a cada minuto; sem limite, um replay de meses
# tentaria caber num tick só.
LOTE = 200


async def _pendentes(s, limite: int) -> list[tuple[int, object, str, bytes]]:  # noqa: ANN001
    """Payloads coletados e ainda não analisados, do mais antigo para o mais novo.

    Ordem cronológica importa: revisões precisam ser aplicadas na ordem em que a
    fonte as emitiu, senão o "estado atual" oscila durante um replay.
    """
    linhas = (
        await s.execute(
            text(
                """
                SELECT r.id, r.fetched_at, r.source_id, b.body
                FROM raw_payloads r
                JOIN payload_bodies b ON b.sha256 = r.body_sha256
                LEFT JOIN parse_runs p
                  ON p.raw_payload_id = r.id AND p.raw_fetched_at = r.fetched_at
                WHERE p.raw_payload_id IS NULL AND r.http_status = 200
                ORDER BY r.fetched_at, r.id
                LIMIT :limite
                """
            ),
            {"limite": limite},
        )
    ).all()
    return [(r.id, r.fetched_at, r.source_id, r.body) for r in linhas]


async def analisar_pendentes(limite: int = LOTE) -> dict[str, int]:
    """Analisa o que estiver pendente. Idempotente por construção."""
    total = {"payloads": 0, "novos": 0, "vistos": 0, "erros": 0}

    async with sessao() as s:
        pendentes = await _pendentes(s, limite)

    for raw_id, fetched_at, source_id, corpo in pendentes:
        try:
            observacoes = conector(source_id).analisar(bytes(corpo))
        except Exception as exc:  # noqa: BLE001
            # Falha de parse não pode travar a fila: registra e segue. O bruto
            # continua guardado, então corrigir o parser e apagar esta linha
            # reprocessa sem perda.
            async with sessao() as s:
                await s.execute(
                    pg_insert(ParseRun)
                    .values(
                        raw_payload_id=raw_id,
                        raw_fetched_at=fetched_at,
                        tenant_id=TENANT_SISTEMA,
                        source_id=source_id,
                        erro=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                    .on_conflict_do_nothing()
                )
            total["erros"] += 1
            _log.error("parse_falhou", raw_payload_id=raw_id, source_id=source_id, erro=str(exc))
            continue

        linhas = [
            {
                "tenant_id": TENANT_SISTEMA,
                "source_id": source_id,
                "source_event_id": o.source_event_id,
                "raw_payload_id": raw_id,
                "raw_fetched_at": fetched_at,
                "observed_at": o.observed_at,
                "source_updated_at": o.source_updated_at,
                "event_type": o.event_type,
                "geom": f"SRID=4326;POINT({o.lon} {o.lat})",
                "lugar": o.lugar,
                "magnitude": o.magnitude,
                "profundidade_km": o.profundidade_km,
                "metrics": o.metrics,
                "xrefs": o.xrefs,
                "status": o.status,
            }
            for o in observacoes
        ]

        async with sessao() as s:
            novos = 0
            if linhas:
                # ON CONFLICT sobre (source_id, source_event_id, source_updated_at):
                # o mesmo evento na mesma revisão aparece em ~60 coletas seguidas, e
                # só a primeira gera linha. Revisão nova gera linha nova — é assim
                # que o append-only acontece sem UPDATE.
                #
                # A contagem vem de RETURNING, não de `rowcount`: em INSERT com ON
                # CONFLICT DO NOTHING o driver devolve -1 (desconhecido), e somar
                # isso dava contagem negativa. Com RETURNING, linha em conflito
                # simplesmente não volta.
                #
                # Uma instrução para o lote inteiro, não uma por observação: num
                # replay de meses a diferença é entre uma ida ao banco e milhares.
                resultado = await s.execute(
                    pg_insert(SourceRecord)
                    .values(linhas)
                    .on_conflict_do_nothing(constraint="uq_source_records_revisao")
                    .returning(SourceRecord.id)
                )
                novos = len(resultado.fetchall())

            await s.execute(
                pg_insert(ParseRun)
                .values(
                    raw_payload_id=raw_id,
                    raw_fetched_at=fetched_at,
                    tenant_id=TENANT_SISTEMA,
                    source_id=source_id,
                    registros_novos=novos,
                    registros_vistos=len(observacoes),
                )
                .on_conflict_do_nothing()
            )

        total["payloads"] += 1
        total["novos"] += novos
        total["vistos"] += len(observacoes)

    if total["payloads"] or total["erros"]:
        _log.info("parse_lote", **total)
    return total


async def reprocessar(source_id: str | None = None) -> int:
    """Apaga o progresso de análise para forçar replay do bruto já coletado.

    É a operação que justifica guardar ``payload_raw``: corrigir o parser e
    reconstruir o histórico normalizado sem depender da fonte.
    """
    async with sessao() as s:
        stmt = delete(ParseRun)
        if source_id:
            stmt = stmt.where(ParseRun.source_id == source_id)
        n = (await s.execute(stmt)).rowcount or 0
    _log.info("parse_reprocessar", source_id=source_id, apagados=n)
    return n


async def pendencia() -> int:
    """Quantos payloads aguardam análise. Alimenta o /saude."""
    async with sessao() as s:
        return (
            await s.execute(
                text(
                    """
                    SELECT count(*) FROM raw_payloads r
                    LEFT JOIN parse_runs p
                      ON p.raw_payload_id = r.id AND p.raw_fetched_at = r.fetched_at
                    WHERE p.raw_payload_id IS NULL AND r.http_status = 200
                    """
                )
            )
        ).scalar_one()


__all__ = ["analisar_pendentes", "pendencia", "reprocessar"]
