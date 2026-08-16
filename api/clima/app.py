"""API operacional. **Não** é a API do produto — essa é a Fase 3.

Existe por um motivo só: o deploy da Fase 0 acontece num VPS e precisa de uma
forma de responder "a coleta está íntegra?" sem abrir o banco. Nenhum endpoint
aqui serve dado de evento, e nenhum serve payload de fonte.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from clima.db import encerrar, sessao
from clima.ingest import verificar
from clima.logs import configurar


@asynccontextmanager
async def ciclo(app: FastAPI):  # noqa: ANN201
    configurar()
    yield
    await encerrar()


app = FastAPI(title="Clima Global — operação", version="0.1.0", lifespan=ciclo)


@app.get("/saude")
async def saude() -> JSONResponse:
    """Integridade da coleta. 200 se íntegra, 503 se há lacuna, silêncio ou DEFAULT ocupada."""
    rel = await verificar()
    corpo: dict[str, Any] = {
        "saudavel": rel.saudavel,
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
