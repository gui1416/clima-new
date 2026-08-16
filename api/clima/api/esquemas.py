"""Contratos de resposta da API de produto.

Duas regras do CLAUDE.md são estruturais aqui, não comentários:

1. **Severidade nunca viaja sozinha.** ``EventoResumo`` exige `magnitude` e
   `metrica_rotulo` ao lado de `severidade`. Um cliente não consegue montar uma
   resposta com a faixa sem a grandeza que a originou.
2. **Fonte `interna` não é redistribuída.** Nada aqui expõe payload de fonte, e
   `Procedencia` omite o conteúdo de fonte restrita, mantendo só a contagem.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Severidade = Literal["critical", "high", "moderate"]


class Procedencia(BaseModel):
    """O que uma fonte afirma sobre o evento.

    A base do painel de procedência. Enquanto há uma fonte só, esta lista tem um
    item — e é honesto que tenha: o valor do produto aparece quando são várias e
    elas discordam.
    """

    fonte: str
    nome: str
    source_event_id: str
    observado_em: datetime
    revisado_em: datetime
    revisoes: int
    status: str
    magnitude: float | None = None
    profundidade_km: float | None = None
    lugar: str | None = None
    atribuicao: str | None = None
    # Só para fonte com redistribuição restrita: o payload não sai, a existência sim.
    conteudo_restrito: bool = False


class EventoResumo(BaseModel):
    id: str
    titulo: str
    tipo: str
    lugar: str | None
    lat: float
    lon: float
    ocorrido_em: datetime
    atualizado_em: datetime

    severidade: Severidade
    # Obrigatórios de propósito: é o que impede a severidade de aparecer sozinha.
    magnitude: float | None = Field(...)
    metrica_rotulo: str = Field(...)
    profundidade_km: float | None

    # Quantas fontes independentes confirmam. É a métrica do diferencial — e
    # enquanto o motor de correlação não existe, vale 1 para tudo.
    fontes_confirmando: int
    revisoes: int
    status: str


class EventoDetalhe(EventoResumo):
    metricas: dict[str, Any]
    xrefs: dict[str, Any]
    procedencia: list[Procedencia]


class Pagina(BaseModel):
    total: int
    itens: list[EventoResumo]
    # Marca honesta do estado do produto, em toda resposta de lista.
    deduplicado: bool = False
    aviso: str | None = None


class Estatisticas(BaseModel):
    eventos_total: int
    por_severidade: dict[str, int]
    por_status: dict[str, int]
    magnitude_maxima: float | None
    ultimo_evento_em: datetime | None
    janela_horas: int
    fontes_ativas: int
    deduplicado: bool = False
