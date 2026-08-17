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
    """Uma fonte que compõe o evento canônico."""

    fonte: str
    nome: str
    source_event_id: str
    observado_em: datetime
    revisado_em: datetime
    status: str
    atribuicao: str | None = None
    # Fonte com redistribuição restrita: a existência sai, o conteúdo não.
    conteudo_restrito: bool = False


class ValorDeFonte(BaseModel):
    fonte: str
    valor: Any | None
    vencedor: bool
    conteudo_restrito: bool = False


class CampoDivergente(BaseModel):
    """O que cada fonte afirma sobre um campo, e qual valor foi adotado.

    **Este é o painel de procedência**, e é a razão de o produto existir. Consolidar
    escondendo a discordância repetiria o problema: cinco fontes que divergem e
    ninguém sabe no quê. Aqui a divergência é o dado.
    """

    campo: str
    valores: list[ValorDeFonte]
    # Verdadeiro quando as fontes não afirmam o mesmo valor.
    divergente: bool


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

    # Quantas fontes independentes confirmam. É a métrica do diferencial, e agora
    # vem do motor de correlação em vez de ser 1 fixo.
    fontes_confirmando: int
    fontes: list[str]
    # 0 a 1. Sobe com fontes independentes, desce com discordância entre elas.
    # Nunca aparece sozinha: `fontes_confirmando` viaja ao lado, por contrato.
    confianca: float
    snapshots: int
    status: str


class EventoDetalhe(EventoResumo):
    metricas: dict[str, Any]
    procedencia: list[Procedencia]
    campos: list[CampoDivergente]


class Pagina(BaseModel):
    total: int
    itens: list[EventoResumo]
    # Os itens são eventos canônicos, saídos do motor de correlação. `true` não
    # significa que o portão G2 foi atendido — significa que houve consolidação.
    deduplicado: bool = True
    aviso: str | None = None


class Estatisticas(BaseModel):
    eventos_total: int
    por_severidade: dict[str, int]
    por_status: dict[str, int]
    magnitude_maxima: float | None
    ultimo_evento_em: datetime | None
    janela_horas: int
    fontes_ativas: int
    eventos_multifonte: int
    deduplicado: bool = True
