"""``payload_raw``: o ativo de longo prazo. Imutável, sem UPDATE, sem DELETE.

Correção em relação ao esboço do plano (§4), que guardava ``body`` dentro de
``raw_payloads``: o corpo foi separado num armazenamento endereçado por conteúdo.

A razão é concreta. O feed horário do USGS é consultado a cada 60 s e devolve o
mesmo corpo na maior parte das vezes; requisição condicional resolve muitos
casos, mas não todos (a fonte pode não mandar ETag, ou mudar um campo de
timestamp sem mudar os eventos). Guardar o corpo por fetch multiplicaria o
armazenamento por ~60 sem ganho de informação. O esboço original tinha um índice
único em ``(source_id, body_sha256, fetched_at)`` que, por incluir a chave de
partição, nunca deduplicaria nada.

Divisão adotada:

* :class:`CorpoPayload` — um corpo distinto, uma linha, endereçado pelo sha256.
* :class:`RawPayload` — uma linha por *fetch*, apontando para o corpo.

Nada é perdido: toda coleta continua registrada individualmente (que é o que
garante a auditoria de continuidade) e todo corpo distinto continua preservado
byte a byte (que é o que garante o replay de parser).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, ForeignKeyConstraint, Index, SmallInteger, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from clima.models.base import Base


class CorpoPayload(Base):
    """Corpo bruto, endereçado por conteúdo. Nunca sobrescrito."""

    __tablename__ = "payload_bodies"

    sha256: Mapped[bytes] = mapped_column(primary_key=True)
    body: Mapped[bytes]
    bytes_total: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str | None]
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RawPayload(Base):
    """Uma coleta. Particionada por mês em ``fetched_at``.

    O DDL real (particionamento, partição DEFAULT, RLS) está na migration 001 —
    este modelo só descreve a forma para o ORM. Não gere DDL daqui.
    """

    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, primary_key=True)
    # A chave de partição precisa entrar na PK de tabela particionada.
    fetched_at: Mapped[datetime] = mapped_column(
        primary_key=True, server_default=func.now()
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    ingest_run_id: Mapped[int] = mapped_column(BigInteger)

    url: Mapped[str]
    http_status: Mapped[int] = mapped_column(SmallInteger)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    body_sha256: Mapped[bytes]

    __table_args__ = (
        ForeignKeyConstraint(["body_sha256"], ["payload_bodies.sha256"]),
        Index("ix_raw_payloads_source_fetched", "source_id", "fetched_at"),
    )
