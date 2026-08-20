# Repository Guidelines

## Project Structure & Module Organization

- `api/clima/` contains the FastAPI backend. Connectors live in `connectors/`, ingestion in `ingest/`, correlation logic in `correlation/`, and HTTP routes in `api/`.
- `api/tests/` holds unit tests; database-dependent tests are under `api/tests/integracao/`. Alembic migrations live in `api/migrations/versions/`.
- `web/src/` contains the React and TypeScript application, with map components in `mapa/`, data access in `dados/`, and shared CSS in `estilos/`.
- `docs/` contains architecture and delivery plans. `mobile/` is reserved and outside v1. Treat `clima-global-prototipo-v2.html` as a frozen visual reference, not production code.

## Build, Test, and Development Commands

- `docker compose up -d --build`: start the API, workers, Redis, and PostGIS development stack.
- `./scripts/testar.sh`: build an isolated Docker test stack, apply migrations, and run pytest. Pass filters through, for example `./scripts/testar.sh -k rls`.
- From `api/`, `pytest --ignore=tests/integracao` runs unit tests without infrastructure; `ruff check clima && mypy clima` runs linting and strict type checks.
- From `web/`, run `npm install`, then `npm run dev` for Vite. Use `npm run build` for type-checking plus a production build, and `npm run verificar` for the headless rendering check.

## Coding Style & Naming Conventions

Python targets 3.12, uses four-space indentation, complete type annotations, and a 100-character line limit enforced by Ruff. Follow `snake_case` for modules/functions and `PascalCase` for classes. Tests use `test_<behavior>` names.

TypeScript runs in strict mode. Use two-space indentation, `camelCase` for values/functions, and `PascalCase` for React components. Keep user-facing copy and domain vocabulary in Brazilian Portuguese. Reuse CSS custom properties from `web/src/estilos/tokens.css`; avoid literal colors.

## Testing Guidelines

Use pytest and pytest-asyncio for backend coverage. Add fixture payloads under `api/tests/fixtures/`. Changes involving persistence, RLS, partitions, migrations, or API/database interaction require integration coverage. Frontend changes must pass `npm run build`; map or UI rendering changes should also pass `npm run verificar`.

## Commit & Pull Request Guidelines

History favors concise, lowercase, imperative Portuguese subjects, often scoped, such as `web: corrige renderização do mapa`. Keep commits focused. Pull requests should explain the user-visible outcome, call out schema or configuration changes, link related issues, list validation commands, and include screenshots for UI changes.

## Data Safety & Configuration

Copy `.env.example` and `api/.env.example`; keep matching database passwords and never commit secrets. Preserve append-only behavior for raw payloads and source records. Do not autogenerate migrations for partitioned raw tables, and access tenant data through the configured non-superuser application role so forced RLS remains effective.
