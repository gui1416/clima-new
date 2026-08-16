FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY clima ./clima
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 10001 clima && chown -R clima:clima /app
USER clima

CMD ["uvicorn", "clima.app:app", "--host", "0.0.0.0", "--port", "8000"]


# Estágio de teste: mesma imagem, mais as dependências de dev e a suíte.
# Usado só por compose.test.yaml (build.target: test) — a imagem de produção
# não carrega pytest.
FROM base AS test

USER root
RUN pip install --no-cache-dir ".[dev]"
COPY tests ./tests
RUN chown -R clima:clima /app
USER clima

CMD ["pytest", "-q"]
