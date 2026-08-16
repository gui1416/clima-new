"""Engine, sessões e o contexto de tenant.

RLS está ativa e *forçada* em todas as tabelas com ``tenant_id``. A política lê
o GUC ``clima.tenant_id``; sem ele, nenhuma linha é visível. Isso é
intencionalmente fail-closed — esquecer de abrir a sessão com um tenant devolve
zero linhas, não o banco inteiro.

Consequência prática: **toda** leitura ou escrita de dado de tenant precisa
passar por :func:`sessao`. Uma sessão crua do engine não vê nada.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from clima.config import TENANT_SISTEMA, config

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            config().database_url_async,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def sessao(tenant_id: UUID = TENANT_SISTEMA) -> AsyncIterator[AsyncSession]:
    """Sessão com o tenant fixado para a transação inteira.

    ``SET LOCAL`` só vale dentro de transação e é revertido no commit/rollback,
    então não há risco de vazar o tenant para a próxima conexão do pool.
    """
    async with sessionmaker()() as s:
        async with s.begin():
            await s.execute(
                text("SELECT set_config('clima.tenant_id', :t, true)"),
                {"t": str(tenant_id)},
            )
            yield s


async def encerrar() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
