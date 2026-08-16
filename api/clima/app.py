"""A aplicação: operação em ``/saude``, produto em ``/eventos`` e ``/estatisticas``.

Nenhum endpoint serve payload bruto de fonte. O conteúdo de fonte com
``redistribuicao = 'interna'`` é removido na serialização (ver
``clima/api/eventos.py``), o que mantém o portão G4 válido por construção.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from clima.api import router_eventos
from clima.db import encerrar, sessao
from clima.ingest import verificar
from clima.ingest.parser import pendencia
from clima.logs import configurar


@asynccontextmanager
async def ciclo(app: FastAPI):  # noqa: ANN201
    configurar()
    yield
    await encerrar()


app = FastAPI(
    title="Clima Global",
    version="0.1.0",
    lifespan=ciclo,
    description=(
        "Consolidação de eventos climáticos e desastres naturais. "
        "**Sem deduplicação entre fontes ainda** — cada evento é o registro de uma "
        "fonte só, e as respostas trazem `deduplicado: false`. O motor de "
        "correlação é a Fase 2 do plano."
    ),
)
# Prefixo /api não é enfeite: sem ele, o caminho da API colide com a rota do SPA.
# `/eventos` no navegador devolvia o JSON em vez da aplicação, porque o proxy do
# dev-server casa antes do fallback de SPA — e em produção, atrás do mesmo host, o
# problema é o mesmo. Operação fica fora do prefixo (/saude) porque não colide com
# rota nenhuma da interface.
app.include_router(router_eventos, prefix="/api")


@app.get("/saude")
async def saude() -> JSONResponse:
    """Integridade da coleta. 200 se íntegra, 503 se há lacuna, silêncio ou DEFAULT ocupada."""
    rel = await verificar()
    # Fila de análise: coleta íntegra com parser parado ainda é problema —
    # o dado entra e não chega ao produto.
    aguardando = await pendencia()
    corpo: dict[str, Any] = {
        "saudavel": rel.saudavel,
        "payloads_aguardando_analise": aguardando,
        "lacunas": [
            {
                "source_id": g.source_id,
                "de": g.de.isoformat(),
                "ate": g.ate.isoformat(),
                "duracao_seg": int(g.duracao.total_seconds()),
            }
            for g in rel.lacunas
        ],
        "silenciosas": [s.source_id for s in rel.silenciosas],
        "linhas_na_particao_default": rel.linhas_na_default,
    }
    return JSONResponse(corpo, status_code=200 if rel.saudavel else 503)


@app.get("/saude/fontes")
async def saude_fontes() -> list[dict[str, Any]]:
    async with sessao() as s:
        linhas = (await s.execute(text("SELECT * FROM v_saude_fontes ORDER BY source_id"))).all()
    return [dict(r._mapping) for r in linhas]
