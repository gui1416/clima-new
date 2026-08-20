# api — back-end

FastAPI, PostgreSQL/PostGIS e ARQ. O backend coleta payloads imutáveis, normaliza
observações, correlaciona fontes e serve eventos canônicos com procedência.

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
├─ connectors/        coleta e normalização, um módulo por fonte
├─ correlation/       deduplicação, clustering e síntese canônica
├─ ingest/            runner, parser, partições e continuidade
├─ api/               eventos, estatísticas e fila de revisão
├─ workers/           agendamento ARQ
└─ app.py             aplicação FastAPI e endpoints operacionais
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

## Operação

- `GET /saude` verifica lacunas, fontes silenciosas, parser e partições.
- `GET /metricas` expõe contadores HTTP no formato Prometheus.
- `GET /api/tiles/{z}/{x}/{y}.mvt` entrega tiles vetoriais.
- `WS /api/eventos/stream?desde=<ISO-8601>` entrega deltas e heartbeat. Sem
  `desde`, o corte é **agora**: um fluxo ao vivo entrega o que mudou a partir da
  conexão, e despejar o histórico na abertura seria o oposto de delta. O padrão
  anterior era `datetime.min.astimezone()`, que no Linux levanta
  `ValueError: year 0 is out of range` — o `except ValueError` escrito para
  ISO-8601 malformado engolia isso e recusava com 1008 **toda** conexão sem
  `desde`, que é toda primeira conexão de todo cliente. O uvicorn registrava
  `connection open` normalmente e só o cliente via a recusa. Coberto por
  `test_fluxo_aceita_conexao_sem_desde`.
- `/api/revisoes` lista e decide casos incertos; exige `X-API-Key` igual a
  `ADMIN_API_KEY`.

Configure `ALERT_WEBHOOK_URL` para receber falhas de continuidade. Backups podem
ser gerados com `./scripts/backup-backend.sh`; valide cada arquivo com
`./scripts/verificar-restauracao.sh caminho.dump`.

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

**Ao criar tabela nova com `tenant_id`, escreva uma política por comando que a
tabela realmente usa.** Com RLS forçada, um comando sem política não dá erro — ele
simplesmente não afeta linha nenhuma. A migration 003 existe porque a 001 criou
só `FOR SELECT` e `FOR INSERT`, e o `UPDATE` que fecha o `ingest_run` passou meses
de código sem nunca alterar nada: `resultado` ficava NULL, e com isso a saúde das
fontes, a detecção de lacuna e a requisição condicional mentiam juntas. O dado
bruto estava correto; a instrumentação que deveria provar isso é que estava
quebrada. Nenhuma exceção em lugar nenhum.

`raw_payloads` e `payload_bodies` continuam sem política de `UPDATE`/`DELETE` de
propósito — ali a ausência é a garantia de imutabilidade.

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

Toda coleta continua registrada (é o que prova continuidade) e todo corpo
distinto continua preservado byte a byte (é o que permite replay de parser).

**Ressalva medida em execução real:** para o USGS a deduplicação quase nunca
dispara. O feed embute `metadata.generated`, um timestamp que muda a cada minuto,
então dois corpos com as mesmas features byte a byte têm sha256 diferentes — e
pela mesma razão o `Last-Modified` é bumpado a cada minuto e não há 304 (o USGS
não manda `ETag`). Custo medido: ~8,2 KB × 1440/dia ≈ 11,8 MB/dia cru, ~2,4 MB/dia
comprimido, perto de **0,9 GB/ano só do USGS**.

A separação em duas tabelas continua valendo — deduplicar por conteúdo é grátis e
dispara em fontes sem timestamp embutido — mas não se deve normalizar o corpo
antes de hashear: isso levaria conhecimento de formato para dentro da camada
crua, o acoplamento que `fetch`/`parse` separados existem para evitar. Detalhes em
`clima/models/raw.py`.

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
