"""Manutenção das partições mensais de ``raw_payloads``.

Roda com folga de meses à frente. A partição DEFAULT existe como rede de
segurança para o caso de este job falhar — sem ela, mês virado sem partição faz
o INSERT da coleta falhar, que é o único erro irrecuperável do projeto.

Contrapartida conhecida: enquanto houver linha na DEFAULT, criar a partição do
mês correspondente falha. Por isso :func:`linhas_na_default` existe e é
verificada junto com a continuidade.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from clima.config import config
from clima.db import sessao
from clima.logs import log

_log = log("particoes")


def _add_meses(d: date, n: int) -> date:
    mes = d.month - 1 + n
    return date(d.year + mes // 12, mes % 12 + 1, 1)


async def garantir_particoes() -> list[str]:
    """Cria a partição do mês corrente e das próximas, de forma idempotente."""
    inicio = date.today().replace(day=1)
    criadas: list[str] = []
    async with sessao() as s:
        for i in range(config().particoes_futuras + 1):
            nome = (
                await s.execute(
                    text("SELECT clima_ensure_raw_partition(:m)"),
                    {"m": _add_meses(inicio, i)},
                )
            ).scalar_one()
            criadas.append(nome)
    _log.info("particoes_garantidas", particoes=criadas)
    return criadas


async def linhas_na_default() -> int:
    """Quantas coletas caíram na partição DEFAULT. Deve ser sempre zero."""
    async with sessao() as s:
        return (
            await s.execute(text("SELECT linhas FROM v_alarme_particao_default"))
        ).scalar_one()
