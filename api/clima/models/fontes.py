from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from clima.dominio import Redistribuicao, ResultadoColeta
from clima.models.base import Base


class Fonte(Base):
    """Registro de conectores. Global, não pertence a tenant.

    ``redistribuicao`` não é anotação — é a trava. Ver :mod:`clima.dominio`.
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(primary_key=True)  # 'usgs', 'gdacs', 'nasa_firms'
    nome: Mapped[str]
    # Text explícito, não o mapeamento automático de Enum. Duas razões: o banco
    # guarda text + CHECK (não um ENUM nativo), e `sqlalchemy.Enum` persistiria o
    # *nome* do membro ('LIVRE') em vez do valor ('livre'), estourando o CHECK.
    # StrEnum já é str, então o valor vai correto numa coluna de texto.
    redistribuicao: Mapped[Redistribuicao] = mapped_column(Text)
    atribuicao_exigida: Mapped[str | None]
    intervalo_poll_seg: Mapped[int] = mapped_column(SmallInteger)
    ativa: Mapped[bool] = mapped_column(default=True)
    observacao: Mapped[str | None]


class ColetaRun(Base):
    """Uma execução de coleta. Log operacional, não observação.

    É a única tabela do pipeline que sofre UPDATE: a linha é aberta antes do
    ``fetch`` e fechada depois. Isso é deliberado — se o processo morrer no meio
    da requisição, a tentativa fica registrada em vez de desaparecer, e a
    detecção de lacuna (:mod:`clima.ingest.continuidade`) enxerga o buraco.

    Guarda também o ``etag``/``last_modified`` da resposta: é daqui que a próxima
    coleta monta a requisição condicional, em vez de manter estado mutável no
    registro de fontes.
    """

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))

    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]

    url: Mapped[str | None]
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    resultado: Mapped[ResultadoColeta | None] = mapped_column(Text)  # ver Fonte.redistribuicao
    erro: Mapped[str | None]
    bytes_recebidos: Mapped[int | None] = mapped_column(BigInteger)
    body_sha256: Mapped[bytes | None]

    etag: Mapped[str | None]
    last_modified: Mapped[str | None]

    __table_args__ = (
        # Sustenta tanto a leitura do último validador quanto a varredura de lacunas.
        Index("ix_ingest_runs_source_started", "source_id", "started_at"),
    )
