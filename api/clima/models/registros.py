from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, ForeignKey, ForeignKeyConstraint, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from clima.models.base import Base


class SourceRecord(Base):
    """Uma observação normalizada, como *uma* fonte a descreveu num instante.

    Não é "o evento" — é o que uma fonte afirmou. A consolidação entre fontes é a
    Fase 2; até lá, cada registro anda sozinho e o produto não tem como dizer
    "quantas fontes confirmam" com número maior que 1.

    Append-only: revisão da fonte vira linha nova, nunca sobrescrita. O estado
    atual é a view ``v_registros_atuais``.
    """

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    source_event_id: Mapped[str]

    raw_payload_id: Mapped[int] = mapped_column(BigInteger)
    raw_fetched_at: Mapped[datetime]

    observed_at: Mapped[datetime]
    source_updated_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())

    event_type: Mapped[str]
    geom: Mapped[str] = mapped_column(Geography(geometry_type="POINT", srid=4326))
    lugar: Mapped[str | None]
    magnitude: Mapped[float | None]
    profundidade_km: Mapped[float | None]

    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    xrefs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(
            ["raw_payload_id", "raw_fetched_at"], ["raw_payloads.id", "raw_payloads.fetched_at"]
        ),
    )


class ParseRun(Base):
    """Progresso de análise, um registro por payload bruto processado.

    Fica fora de ``raw_payloads`` porque lá não há UPDATE — nem por privilégio,
    nem por princípio. Apagar uma linha daqui reprocessa aquele payload, que é o
    mecanismo de replay que justifica guardar o bruto.
    """

    __tablename__ = "parse_runs"

    raw_payload_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_fetched_at: Mapped[datetime] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    parsed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    registros_novos: Mapped[int] = mapped_column(default=0)
    registros_vistos: Mapped[int] = mapped_column(default=0)
    erro: Mapped[str | None]

    __table_args__ = (
        ForeignKeyConstraint(
            ["raw_payload_id", "raw_fetched_at"], ["raw_payloads.id", "raw_payloads.fetched_at"]
        ),
    )
