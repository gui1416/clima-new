# api — back-end

FastAPI, PostgreSQL/PostGIS, ARQ. Estado: **Fase 0** do
[plano](../docs/plano-de-construcao.md) — coleta de `payload_raw` do USGS.

Ainda não existe: parser, motor de correlação, API de produto. Nesta ordem, nas
Fases 1, 2 e 3.

## Subir

```bash
cp .env.example .env && cp ../.env.example ../.env
```

Ajuste a senha nos dois arquivos (precisa ser a mesma) e o e-mail em
`USER_AGENT`. Depois, da raiz do repositório:

```bash
docker compose up -d --build
```

O `migrate` roda antes do `worker` e do `api`. Verificação:

```bash
curl -s localhost:8000/saude | python3 -m json.tool
```

`200` = coleta íntegra. `503` = há lacuna, fonte silenciosa ou linha na partição
DEFAULT — os três estão detalhados no corpo da resposta.

## Estrutura

```
clima/
├─ config.py          configuração e o UUID do tenant de sistema
├─ dominio.py         vocabulários que espelham os CHECKs do banco
├─ db.py              engine, sessões e o contexto de tenant (RLS)
├─ models/            SQLAlchemy
├─ connectors/        um módulo por fonte: coletar() agora, analisar() na Fase 1
├─ ingest/            runner, partições, continuidade
├─ workers/           agendamento ARQ
└─ app.py             API operacional (não é a API do produto)
migrations/           Alembic; DDL de raw_payloads é escrito à mão
```

## Convenção de nomes

Campos técnicos e temporais em inglês (`fetched_at`, `http_status`, `tenant_id`,
`source_id`), campos de domínio em português (`redistribuicao`, `resultado`,
`atribuicao_exigida`). É deliberado: o domínio é brasileiro, a infraestrutura
segue a convenção da linguagem.

## Testes

Unitários, sem infraestrutura:

```bash
pytest --ignore=tests/integracao
```

Suíte completa em Docker — sobe Postgres+PostGIS em tmpfs, aplica migrations,
roda tudo e derruba. Não toca o banco de desenvolvimento:

```bash
./scripts/testar.sh
```

Filtrar (argumentos vão para o pytest): `./scripts/testar.sh -k rls`

Os testes de `tests/integracao/` conectam como `clima_app`, não como dono — é o
que faz os testes de RLS medirem comportamento real em vez de nada.

## Multi-tenancy

`tenant_id` existe desde a migration 001 com RLS **forçada**, porque retrofitar
multi-tenancy numa base com dados reais é reescrita.

**Dois papéis no banco, e isso não é opcional.** No PostgreSQL, superusuários e
papéis com `BYPASSRLS` ignoram row-level security por completo, e `FORCE ROW
LEVEL SECURITY` só sujeita o *dono* da tabela. A imagem oficial do Postgres cria
`POSTGRES_USER` como superusuário — se a aplicação conectar com ele, toda a RLS
do projeto é decoração e nada acusa. Então:

| Papel | Uso | DSN |
|---|---|---|
| `POSTGRES_USER` (dono) | migrations e administração | `DATABASE_URL_ADMIN` |
| `clima_app` | a aplicação | `DATABASE_URL` |

`clima_app` é criado no initdb por `db/init/10-papel-app.sh` e recebe privilégios
mínimos na migration 002. Não tem `DELETE` nem `UPDATE` em
`raw_payloads`/`payload_bodies`: a imutabilidade do ativo histórico é privilégio
negado, não só disciplina.

`tests/integracao/test_rls.py::test_papel_app_nao_ignora_rls` falha alto se um
deploy for configurado com papel superusuário.

Uma ressalva ao princípio, adotada aqui de forma consciente: a ingestão é
**compartilhada**. Uma coleta do USGS serve todos os clientes; duplicar o fetch
por tenant seria absurdo. Então existe um **tenant de sistema**
(`00000000-0000-0000-0000-000000000001`) que possui as linhas do pipeline, e a
política de RLS permite que qualquer tenant *leia* as linhas dele, mas *escreva*
apenas as próprias. O que será genuinamente por cliente — chaves de API, alertas,
webhooks, visões salvas — nasce já com a coluna no lugar.

`payload_bodies` é a única tabela do pipeline sem `tenant_id`, porque a
deduplicação por sha256 é o ponto dela e um mesmo corpo do USGS é o mesmo byte
para todos. Só é alcançável via `raw_payloads`, que é tenant-scoped.

**Consequência operacional:** RLS forçada é fail-closed. Uma sessão sem
`clima.tenant_id` definido não vê linha nenhuma — parece banco vazio, não erro de
permissão. Toda leitura passa por `clima.db.sessao()`.

## payload_raw

Duas tabelas, não uma:

- `payload_bodies` — corpo endereçado pelo sha256. Um corpo distinto, uma linha.
- `raw_payloads` — uma linha por coleta, particionada por mês, apontando para o corpo.

O motivo está no docstring de `clima/models/raw.py`: o feed horário do USGS é
sondado a cada 60 s e devolve o mesmo corpo na maior parte das vezes. Guardar o
corpo por fetch multiplicaria o armazenamento sem ganho de informação. Toda
coleta continua registrada (é o que prova continuidade) e todo corpo distinto
continua preservado byte a byte (é o que permite replay de parser).

Nunca `UPDATE` nem `DELETE` nessas duas tabelas. `ingest_runs` é a exceção
declarada: é log operacional e a linha é aberta antes do fetch e fechada depois,
justamente para que uma queda no meio da requisição deixe rastro.

## Licença como código

`sources.redistribuicao ∈ {livre, atribuicao, interna}`. Copernicus e INMET
nascem `interna`: participam da correlação e do cálculo de confiança, mas o
payload não sai numa resposta de API. Só saem de `interna` com resposta jurídica
por escrito — portão **G4** do plano.

Quando a API de produto existir (Fase 3), isto precisa de teste automatizado:
nenhum `response_model` serializa campo originado de fonte `interna`.

## Migrations

```bash
alembic upgrade head
alembic upgrade head --sql    # revisa o SQL sem banco
```

Não use `--autogenerate` para mexer em `raw_payloads` ou `payload_bodies`:
particionamento, RLS e partição DEFAULT não são representáveis nos modelos e o
diff tentaria removê-los. `migrations/env.py` filtra essas tabelas justamente
para que um autogenerate acidental não as destrua.

## Ambiente de desenvolvimento

`pyproject.toml` declara `requires-python = ">=3.12"`; a imagem é 3.12 e é o alvo
testado. Python 3.14 pode não ter wheels de `psycopg[binary]` ainda — se for
rodar fora do Docker, prefira 3.12 ou 3.13.
