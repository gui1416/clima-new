"""Proteções HTTP e métricas pequenas, sem depender de um fornecedor externo."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware

from clima.config import config
from clima.logs import log

_log = log("http")
_requisicoes: Counter[tuple[str, str, int]] = Counter()


class OperacaoMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        inicio = time.monotonic()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        if request.url.path not in {"/saude", "/metricas"} and not await _permitida(request):
            resposta = Response("limite de requisições excedido", status_code=429)
        else:
            resposta = await call_next(request)
        resposta.headers["X-Request-ID"] = request_id
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        _requisicoes[(request.method, request.url.path, resposta.status_code)] += 1
        _log.info(
            "requisicao_http",
            request_id=request_id,
            metodo=request.method,
            caminho=request.url.path,
            status=resposta.status_code,
            duracao_ms=round((time.monotonic() - inicio) * 1000, 2),
        )
        return resposta


async def _permitida(request: Request) -> bool:
    """Janela fixa no Redis; falha aberta para não derrubar leitura se Redis cair."""
    cfg = config()
    cliente = request.client.host if request.client else "desconhecido"
    janela = int(time.time() // 60)
    chave = f"rate:{cliente}:{janela}"
    redis = Redis.from_url(cfg.redis_url, decode_responses=True)
    try:
        async with asyncio.timeout(0.25):
            atual = await redis.incr(chave)
            if atual == 1:
                await redis.expire(chave, 70)
        return bool(atual <= cfg.rate_limit_por_minuto)
    except Exception as exc:  # noqa: BLE001
        _log.warning("rate_limit_indisponivel", erro=str(exc))
        return True
    finally:
        await redis.aclose()


def metricas_prometheus() -> str:
    linhas = [
        "# HELP clima_http_requests_total Requisições HTTP",
        "# TYPE clima_http_requests_total counter",
    ]
    for (metodo, caminho, status), total in sorted(_requisicoes.items()):
        linhas.append(
            "clima_http_requests_total"
            f'{{method="{metodo}",path="{caminho}",status="{status}"}} {total}'
        )
    return "\n".join(linhas) + "\n"
