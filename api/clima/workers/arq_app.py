"""Agendador. `arq clima.workers.arq_app.WorkerSettings`

Três tarefas na Fase 0:

* coleta — a cada minuto, no segundo 0;
* partições — diária, com folga de meses à frente;
* continuidade — a cada 5 minutos, e é ela que grita quando algo parou.
"""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from clima.config import config
from clima.db import encerrar
from clima.ingest import coletar_ativas, garantir_particoes, verificar
from clima.correlation import correlacionar
from clima.ingest.parser import analisar_pendentes
from clima.logs import configurar, log

_log = log("worker")


async def tarefa_coletar(ctx: dict[str, Any]) -> dict[str, str]:
    return await coletar_ativas()


async def tarefa_analisar(ctx: dict[str, Any]) -> dict[str, int]:
    return await analisar_pendentes()


async def tarefa_correlacionar(ctx: dict[str, Any]) -> dict[str, int]:
    return (await correlacionar()).como_dict()


async def tarefa_particoes(ctx: dict[str, Any]) -> list[str]:
    return await garantir_particoes()


async def tarefa_continuidade(ctx: dict[str, Any]) -> dict[str, Any]:
    rel = await verificar()
    return {
        "saudavel": rel.saudavel,
        "lacunas": len(rel.lacunas),
        "silenciosas": [s.source_id for s in rel.silenciosas],
        "linhas_na_default": rel.linhas_na_default,
    }


async def ao_iniciar(ctx: dict[str, Any]) -> None:
    configurar()
    _log.info("worker_iniciado")


async def ao_encerrar(ctx: dict[str, Any]) -> None:
    await encerrar()
    _log.info("worker_encerrado")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(config().redis_url)
    on_startup = ao_iniciar
    on_shutdown = ao_encerrar

    cron_jobs = [
        # second=0 com minute em aberto: uma vez por minuto.
        cron(tarefa_coletar, second=0, run_at_startup=True, max_tries=1),
        # 20 s depois da coleta: o payload do minuto já está gravado quando o
        # parser roda, então o atraso entre observar e publicar fica abaixo de 1 min.
        cron(tarefa_analisar, second=20, run_at_startup=True, max_tries=1),
        # 40 s: depois da coleta (0 s) e da análise (20 s), para correlacionar o
        # que acabou de entrar dentro do mesmo minuto.
        cron(tarefa_correlacionar, second=40, run_at_startup=True, max_tries=1),
        cron(tarefa_particoes, hour=3, minute=10, run_at_startup=True),
        cron(tarefa_continuidade, minute=set(range(0, 60, 5)), second=30),
    ]
