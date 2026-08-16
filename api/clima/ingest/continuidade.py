"""Verificação de continuidade da coleta — o que prova o portão G1.

"O coletor está rodando" não é a afirmação que interessa. A afirmação que
interessa é "não existe lacuna no histórico". São coisas diferentes: um processo
vivo que falha silenciosamente em toda requisição parece saudável por fora.

Três perguntas, nesta ordem de gravidade:

1. Alguma coleta caiu na partição DEFAULT? (bug estrutural, bloqueia partição)
2. Alguma fonte ativa está silenciosa? (coleta parada agora)
3. Existe lacuna acima do limite no histórico? (coleta parou em algum momento)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text

from clima.config import config
from clima.db import sessao
from clima.ingest.particoes import linhas_na_default
from clima.logs import log

_log = log("continuidade")


@dataclass(frozen=True, slots=True)
class Lacuna:
    source_id: str
    de: datetime
    ate: datetime
    duracao: timedelta


@dataclass(frozen=True, slots=True)
class Silencio:
    source_id: str
    ultima_coleta_ok: datetime | None
    intervalo_poll_seg: int


@dataclass(frozen=True, slots=True)
class Relatorio:
    lacunas: list[Lacuna]
    silenciosas: list[Silencio]
    linhas_na_default: int

    @property
    def saudavel(self) -> bool:
        return not self.lacunas and not self.silenciosas and self.linhas_na_default == 0


async def lacunas(janela: timedelta = timedelta(days=1)) -> list[Lacuna]:
    limite = timedelta(seconds=config().lacuna_alarme_seg)
    async with sessao() as s:
        linhas = (
            await s.execute(
                text(
                    """
                    SELECT source_id, de, ate, duracao
                    FROM v_lacunas_coleta
                    WHERE duracao > :limite AND ate > now() - :janela
                    ORDER BY ate DESC
                    """
                ),
                {"limite": limite, "janela": janela},
            )
        ).all()
    return [Lacuna(r.source_id, r.de, r.ate, r.duracao) for r in linhas]


async def silenciosas() -> list[Silencio]:
    """Fontes ativas sem coleta bem-sucedida recente.

    Tolerância: três intervalos de poll, com piso no limite de lacuna. Duas
    falhas seguidas são ruído de rede; três já é problema.
    """
    async with sessao() as s:
        linhas = (
            await s.execute(
                text(
                    """
                    SELECT source_id, ultima_coleta_ok, intervalo_poll_seg
                    FROM v_saude_fontes
                    WHERE ativa
                      AND (
                        ultima_coleta_ok IS NULL
                        OR ultima_coleta_ok < now() - greatest(
                             make_interval(secs => intervalo_poll_seg * 3),
                             make_interval(secs => :piso)
                           )
                      )
                    """
                ),
                {"piso": config().lacuna_alarme_seg},
            )
        ).all()
    return [Silencio(r.source_id, r.ultima_coleta_ok, r.intervalo_poll_seg) for r in linhas]


async def verificar() -> Relatorio:
    rel = Relatorio(
        lacunas=await lacunas(),
        silenciosas=await silenciosas(),
        linhas_na_default=await linhas_na_default(),
    )

    if rel.linhas_na_default:
        _log.error("particao_default_ocupada", linhas=rel.linhas_na_default)
    for s in rel.silenciosas:
        _log.error(
            "fonte_silenciosa", source_id=s.source_id, ultima_coleta_ok=str(s.ultima_coleta_ok)
        )
    for g in rel.lacunas:
        _log.error(
            "lacuna_de_coleta", source_id=g.source_id, de=str(g.de), ate=str(g.ate),
            duracao_seg=int(g.duracao.total_seconds()),
        )
    if rel.saudavel:
        _log.info("continuidade_ok")
    return rel
