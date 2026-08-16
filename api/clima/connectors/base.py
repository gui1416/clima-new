"""Contrato dos conectores.

Dois estágios, deliberadamente separados:

* **coletar** — fala com a rede e devolve bytes crus. É o que existe na Fase 0.
* **analisar** — transforma bytes em ``source_records``. Entra na Fase 1 e lê
  sempre de ``payload_bodies``, nunca da rede.

A separação é a razão prática de ``payload_raw`` existir. Bug de parser vira
replay sobre o histórico já coletado, não perda de dado. Um conector que faça
parse durante o fetch quebra essa garantia e não deve ser aceito em revisão.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

import httpx


@dataclass(frozen=True, slots=True)
class Validadores:
    """Cabeçalhos de cache da última coleta bem-sucedida.

    Persistidos em ``ingest_runs`` em vez de num campo mutável do registro de
    fontes — assim o histórico de coletas continua sendo a única fonte de estado.
    """

    etag: str | None = None
    last_modified: str | None = None

    def cabecalhos(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.etag:
            h["If-None-Match"] = self.etag
        if self.last_modified:
            h["If-Modified-Since"] = self.last_modified
        return h


@dataclass(frozen=True, slots=True)
class Resposta:
    url: str
    http_status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None  # None quando 304: a fonte respondeu, nada mudou
    content_type: str | None = None
    validadores: Validadores = field(default_factory=Validadores)

    @property
    def nao_modificado(self) -> bool:
        return self.http_status == 304


@dataclass(frozen=True, slots=True)
class Observacao:
    """Uma observação normalizada, saída do parser e ainda sem tocar o banco.

    ``xrefs`` é o que torna a correlação da Fase 2 possível de forma determinística:
    identificadores que a própria fonte declara para o mesmo fenômeno.
    """

    source_event_id: str
    observed_at: datetime
    source_updated_at: datetime
    event_type: str
    lat: float
    lon: float
    status: str
    lugar: str | None = None
    magnitude: float | None = None
    profundidade_km: float | None = None
    metrics: dict[str, object] = field(default_factory=dict)
    xrefs: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Conector(Protocol):
    id: str

    async def coletar(self, cliente: httpx.AsyncClient, anteriores: Validadores) -> Resposta:
        """Uma requisição à fonte. Não interpreta o corpo, não grava nada."""
        ...

    def analisar(self, corpo: bytes) -> Sequence[Observacao]:
        """Bytes crus → observações. Puro: sem rede, sem banco, sem relógio.

        Recebe sempre o corpo lido de ``payload_bodies``, nunca uma resposta HTTP
        fresca. É o que faz bug de parser virar replay em vez de perda de dado.
        Ser puro também é o que permite testá-lo contra um payload real gravado.
        """
        ...


def resposta_de_httpx(r: httpx.Response) -> Resposta:
    """Converte a resposta do httpx no formato do pipeline, tratando 304."""
    validadores = Validadores(
        etag=r.headers.get("etag"),
        last_modified=r.headers.get("last-modified"),
    )
    return Resposta(
        url=str(r.request.url),
        http_status=r.status_code,
        headers=dict(r.headers),
        body=None if r.status_code == 304 else r.content,
        content_type=r.headers.get("content-type"),
        validadores=validadores,
    )
