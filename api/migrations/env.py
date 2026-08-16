from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from clima.config import config as app_config
from clima.models import Base

alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata

# Objetos cujo DDL é escrito à mão nas migrations. O autogenerate não representa
# particionamento, RLS nem partição DEFAULT e tentaria removê-los.
GERENCIADAS_A_MAO = {"raw_payloads", "payload_bodies"}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001, ANN201
    if type_ == "table":
        # Partições filhas (raw_payloads_2026_08, raw_payloads_default) nunca
        # devem aparecer num diff.
        if name in GERENCIADAS_A_MAO or (name or "").startswith("raw_payloads_"):
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=app_config().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # psycopg3 serve sync e async com o mesmo DSN; migration é sync de propósito.
    engine = create_engine(app_config().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
