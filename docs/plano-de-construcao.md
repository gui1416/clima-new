# Plano de construção — Clima Global

Documento de trabalho. Deriva de [CLAUDE.md](../CLAUDE.md), que é a raiz de
finalidade e princípios. Se um dos dois mudar, revise o outro.

**Decisões travadas para este plano:** Python + FastAPI no back-end · React +
TypeScript + MapLibre GL no front · execução solo em dedicação integral ·
decisão "dev vs organização" postergada até o portão G3.

---

## 1. A tese, operacionalizada

O produto só existe se o motor de correlação existir. Todo o resto — mapa,
telas, tempo real, relatórios — é infraestrutura de apresentação em torno dele,
e é replicável por qualquer concorrente gratuito.

Isso tem três consequências que governam o plano inteiro:

1. **O motor vem antes da interface de produção.** O protótipo já resolve a
   pergunta "como isso se parece". Não há motivo para reescrevê-lo em React
   antes de haver dado deduplicado real para mostrar.
2. **Existe um portão de qualidade explícito** (G2, §7). Se o motor não atingir
   a precisão mínima, o plano para ali e não avança para a interface. Cortar
   escopo em qualquer outra dimensão é preferível.
3. **Falso merge é pior que falso split.** Unir dois eventos distintos esconde
   um evento real do usuário; deixar duplicatas separadas apenas repete
   informação. O motor é calibrado para **precisão alta, recall moderado**, e a
   dúvida vira estado visível na interface ("possível duplicata") em vez de
   decisão silenciosa.

## 2. Ordem de urgência real

Uma única tarefa deste plano é irreversível se atrasar: **começar a gravar
`payload_raw`**. Dado histórico não é reconstruível retroativamente. Cada dia
sem coleta é um dia permanentemente ausente do ativo de longo prazo da empresa.

Por isso a Fase 0 não termina com "ambiente configurado" — termina com um
coletor bobo em produção gravando respostas cruas do USGS num banco, mesmo sem
parser, sem normalização, sem API e sem interface. É a primeira coisa a
funcionar, não a última.

Todo o resto pode ser refeito. Isto não.

## 3. Arquitetura

```
┌─────────────┐   HTTP/poll    ┌──────────────┐
│  Conectores │ ─────────────► │  raw_payloads│  imutável, particionado por mês
│  (por fonte)│                └──────┬───────┘
└─────────────┘                       │ replay
                                      ▼
                              ┌───────────────┐
                              │   Parsers     │  puros: raw → source_records
                              └──────┬────────┘
                                     ▼
                          ┌────────────────────┐
                          │  source_records    │  append-only, 1 linha/revisão
                          └─────────┬──────────┘
                                    ▼
        ┌───────────────────────────────────────────────┐
        │  Motor de correlação                          │
        │  blocking → xref → score → cluster → síntese  │
        └───────────────────┬───────────────────────────┘
                            ▼
              ┌──────────────────────────────┐
              │ canonical_events             │
              │ canonical_event_snapshots    │  append-only
              │ event_field_claims           │  divergências preservadas
              └──────────┬───────────────────┘
                         │ LISTEN/NOTIFY
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
    REST (leitura)   WebSocket        MVT tiles
                         │             (ST_AsMVT)
                         ▼
              React + MapLibre GL
```

**Separação crítica:** `fetch` e `parse` são estágios distintos e o parser lê
sempre de `raw_payloads`, nunca da rede. Bug de parser é *replay*, não perda de
dado. Essa separação é a razão prática de `payload_raw` existir — sem ela, o
princípio é apenas armazenamento caro.

### Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Banco | PostgreSQL 16 + PostGIS 3.4 | Fonte de verdade geoespacial; índices GIST para as consultas de proximidade do motor |
| API | FastAPI + Pydantic v2 | Serialização tipada; o `response_model` é onde a trava de licença é aplicada (§6) |
| ORM/migrations | SQLAlchemy 2 + GeoAlchemy2 + Alembic | `tenant_id` e RLS desde a migration 001 |
| Workers | ARQ (Redis) | Mais simples que Celery para poucos jobs; agendamento por fonte |
| Geometria | Shapely + pyproj | Clustering de focos, cálculo de distância geodésica, reprojeção |
| Tempo real | Postgres `LISTEN/NOTIFY` → WebSocket | Um componente a menos que Redis pub/sub; suficiente para uma instância. Trocar por Redis só ao escalar horizontalmente |
| Front | Vite + React + TS + MapLibre GL + TanStack Query | Tiles vetoriais reais; tokens de design portados do protótipo |
| Infra v1 | 1 VPS + Docker Compose | Não vale Kubernetes para um operador |

### Estrutura de diretórios

Três pastas de primeiro nível, uma por superfície. Nada de back-end fora de
`/api`: `connectors`, `correlation`, `workers` e `migrations` são subpastas dele,
não irmãs. Só orquestração fica na raiz.

```
clima-new/
├─ clima-global-prototipo-v2.html   # especificação visual, congelada
├─ compose.yaml                     # orquestra o projeto todo
├─ docs/
├─ api/                             # BACK-END inteiro
│  ├─ clima/
│  │  ├─ config.py  dominio.py  db.py  app.py
│  │  ├─ models/                    # SQLAlchemy
│  │  ├─ connectors/                # um módulo por fonte: coletar() + analisar()
│  │  ├─ correlation/               # blocking, features, scoring, clustering, síntese
│  │  ├─ ingest/                    # runner, partições, continuidade
│  │  └─ workers/                   # ARQ: agendador e tarefas
│  ├─ migrations/                   # Alembic
│  ├─ eval/                         # golden set + harness de avaliação
│  └─ tests/
├─ web/                             # FRONT-END web: React + TS + MapLibre GL
└─ mobile/                          # APP MÓVEL (fora da v1, lugar reservado)
```

## 4. Modelo de dados

Esboço das tabelas que carregam as decisões estruturais. `tenant_id` em todas,
com RLS ativa desde o início — retrofitar depois é reescrita.

```sql
-- Registro de conectores. A coluna de licença é o mecanismo estrutural
-- que impede redistribuição indevida (§6), não uma anotação.
CREATE TABLE sources (
  id                    text PRIMARY KEY,          -- 'usgs', 'gdacs', 'firms'
  nome                  text NOT NULL,
  redistribuicao        text NOT NULL              -- 'livre' | 'atribuicao' | 'interna'
    CHECK (redistribuicao IN ('livre','atribuicao','interna')),
  atribuicao_exigida    text,
  intervalo_poll_seg    int NOT NULL
);

-- payload_raw. Imutável. Nunca UPDATE, nunca DELETE.
--
-- CORRIGIDO na implementação da Fase 0: o corpo saiu daqui para um
-- armazenamento endereçado por conteúdo. O esboço acoplava corpo e coleta, e o
-- índice único que pretendia deduplicar incluía a chave de partição
-- (`fetched_at`) — logo, nunca deduplicaria nada.
--
-- MEDIDO depois, contra o feed real: para o USGS a deduplicação quase nunca
-- dispara, porque o feed embute `metadata.generated` e o corpo muda a cada minuto
-- mesmo sem evento novo. Custo real ~0,9 GB/ano comprimido, só do USGS. A
-- separação continua valendo para fontes sem timestamp embutido; normalizar o
-- corpo antes de hashear, não — levaria formato de fonte para a camada crua.
CREATE TABLE payload_bodies (          -- um corpo distinto, uma linha
  sha256        bytea PRIMARY KEY CHECK (length(sha256) = 32),
  body          bytea NOT NULL,
  bytes_total   bigint NOT NULL,
  content_type  text,
  first_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw_payloads (            -- uma linha por coleta
  id            bigserial,
  fetched_at    timestamptz NOT NULL DEFAULT now(),
  tenant_id     uuid NOT NULL,
  source_id     text NOT NULL REFERENCES sources(id),
  ingest_run_id bigint NOT NULL REFERENCES ingest_runs(id),
  url           text NOT NULL,
  http_status   smallint NOT NULL,
  headers       jsonb NOT NULL DEFAULT '{}'::jsonb,
  body_sha256   bytea NOT NULL REFERENCES payload_bodies(sha256),
  PRIMARY KEY (id, fetched_at)
) PARTITION BY RANGE (fetched_at);

-- Rede de segurança: mês virado sem partição faria o INSERT da coleta falhar,
-- que é o único erro irrecuperável do projeto.
CREATE TABLE raw_payloads_default PARTITION OF raw_payloads DEFAULT;

-- Snapshot normalizado. Uma linha por versão observada; jamais sobrescrita.
CREATE TABLE source_records (
  id                bigserial PRIMARY KEY,
  tenant_id         uuid NOT NULL,
  source_id         text NOT NULL REFERENCES sources(id),
  source_event_id   text NOT NULL,
  revision          int  NOT NULL,
  raw_payload_id    bigint NOT NULL,
  observed_at       timestamptz NOT NULL,      -- quando o fenômeno ocorreu
  source_updated_at timestamptz,               -- quando a fonte revisou
  ingested_at       timestamptz NOT NULL DEFAULT now(),
  event_type        text NOT NULL,
  geom              geography(Geometry,4326) NOT NULL,
  metrics           jsonb NOT NULL DEFAULT '{}',   -- {magnitude:6.4, depth_km:34}
  xrefs             jsonb NOT NULL DEFAULT '{}',   -- {usgs:'us7000abcd', glide:'EQ-2026-000123'}
  status            text NOT NULL,                 -- 'ativo'|'encerrado'|'cancelado'
  UNIQUE (source_id, source_event_id, revision)
);
CREATE INDEX ON source_records USING GIST (geom);
CREATE INDEX ON source_records USING BRIN (observed_at);

-- Decisões par-a-par. Auditável: guarda o vetor de features que gerou o score.
CREATE TABLE record_links (
  a_id      bigint NOT NULL REFERENCES source_records(id),
  b_id      bigint NOT NULL REFERENCES source_records(id),
  metodo    text NOT NULL,     -- 'xref' | 'probabilistico' | 'manual'
  veredito  text NOT NULL,     -- 'mesmo' | 'distinto' | 'incerto'
  score     real,
  features  jsonb NOT NULL,
  decidido_em timestamptz NOT NULL DEFAULT now(),
  decidido_por text,
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)
);

-- O evento consolidado e seu histórico append-only.
CREATE TABLE canonical_events (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
  event_type text NOT NULL, first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL
);

CREATE TABLE canonical_event_snapshots (
  canonical_event_id uuid NOT NULL REFERENCES canonical_events(id),
  seq                int  NOT NULL,
  valid_from         timestamptz NOT NULL DEFAULT now(),
  geom               geography(Geometry,4326) NOT NULL,
  metrics            jsonb NOT NULL,
  source_count       int  NOT NULL,
  confianca          real NOT NULL,
  status             text NOT NULL,
  motivo_mudanca     text,          -- 'nova_fonte'|'magnitude_revisada'|'area_ampliada'
  PRIMARY KEY (canonical_event_id, seq)
);

-- A divergência entre fontes, preservada. Base do painel de procedência.
CREATE TABLE event_field_claims (
  canonical_event_id uuid NOT NULL REFERENCES canonical_events(id),
  campo              text NOT NULL,     -- 'magnitude', 'observed_at', 'exposicao'
  source_id          text NOT NULL REFERENCES sources(id),
  valor              jsonb NOT NULL,
  source_record_id   bigint NOT NULL REFERENCES source_records(id),
  PRIMARY KEY (canonical_event_id, campo, source_id)
);
```

O estado atual é uma **view** sobre o último snapshot, nunca uma linha mutável:

```sql
CREATE VIEW v_eventos_atuais AS
SELECT e.*, s.*
FROM canonical_events e
JOIN LATERAL (
  SELECT * FROM canonical_event_snapshots
  WHERE canonical_event_id = e.id ORDER BY seq DESC LIMIT 1
) s ON true;
```

## 5. O motor de correlação

Cinco estágios. O ponto não óbvio está no estágio 2.

### 5.1 Blocking — geração de candidatos

Comparação par-a-par de todos contra todos é inviável e desnecessária.
Candidatos vêm de `ST_DWithin` + janela temporal + compatibilidade de tipo, com
parâmetros **por tipo de evento**, porque a física de cada um é diferente:

| Tipo | Raio | Janela | Razão |
|---|---|---|---|
| Terremoto | 100 km | ±90 s | Epicentro varia entre redes sismográficas; o *origin time* é preciso e discrimina bem |
| Ciclone | 200 km | ±3 h | Boletins saem em horários sinóticos; posição precisa ser interpolada antes de comparar |
| Enchente | 50 km ou interseção de polígono | ±24 h | Evento lento e areal; "início" é definição editorial de cada fonte |
| Incêndio | 10 km entre focos | ±12 h | Requer clustering **antes** da correlação (§5.6) |
| Vulcão | 30 km do edifício | ±24 h | Ancorar no número GVP do vulcão resolve quase tudo |

Tipos incompatíveis nunca são candidatos. Mas atenção à distinção: onda de calor
e incêndio florestal no mesmo lugar não são o mesmo evento — são eventos com
**relação causal**. Isso é uma aresta de outro tipo, modelada depois, não um
merge. Confundir os dois é o erro mais fácil de cometer aqui.

### 5.2 Cruzamento determinístico primeiro

Boa parte do trabalho é de graça e quase todo mundo ignora: **as fontes já se
referenciam mutuamente.**

- USGS expõe em `properties.ids` todos os identificadores das redes
  contribuintes do mesmo sismo.
- GDACS agrega e carrega referência à fonte de origem no seu registro de evento.
- NASA EONET traz um array `sources` com link direto para o boletim original.
- ReliefWeb e vários boletins nacionais carregam o **número GLIDE**, que é
  exatamente uma tentativa de identificador compartilhado entre fontes.
- CAP (NOAA/NWS) tem `references` apontando para o alerta que está atualizando
  ou cancelando.

Onde existe cruzamento explícito, o vínculo é **certo** — grave em
`record_links` com `metodo='xref'` e não gaste score probabilístico nele. O
caminho probabilístico atende somente o que não tem referência.

Esse é o atalho que faz a v1 ser viável em semanas em vez de meses. Os detalhes
exatos de cada campo precisam ser confirmados contra a resposta real de cada
fonte durante o spike do conector — não confie na documentação.

### 5.3 Scoring probabilístico

Para cada par candidato sem xref, um vetor de features → score. Features e peso
inicial (a calibrar contra o golden set, não a chutar em produção):

| Feature | Peso | Nota |
|---|---|---|
| Distância espacial normalizada pelo raio do tipo | alto | |
| Distância temporal normalizada pela janela do tipo | alto | |
| Concordância de métrica primária | alto | Só quando ambos têm grandeza comparável |
| Sobreposição de geometria (IoU) | médio | Para eventos areais |
| Similaridade de topônimo | **baixo** | Nomes divergem entre idiomas; sinal fraco e traiçoeiro |

Modelo: regressão logística sobre o golden set. Deliberadamente simples —
interpretável, treinável com poucas centenas de exemplos, e permite explicar na
interface *por que* dois registros foram unidos. Um modelo mais forte não
melhora nada enquanto o golden set for pequeno.

### 5.4 Clustering

Union-find sobre pares acima do limiar alto. O risco é **encadeamento**: A~B,
B~C, mas A e C são claramente distintos, e a transitividade cega funde os três.

Guarda: após formar o cluster, valida-se o diâmetro (máxima distância
espaço-temporal interna). Cluster que estoura o limite do tipo **não é fundido
em silêncio** — é marcado `incerto` e vai para uma fila de revisão. A interface
mostra "possível duplicata"; o merge só acontece com decisão humana registrada
em `record_links` como `metodo='manual'`.

### 5.5 Síntese canônica

Cluster → um evento canônico. Duas regras:

**Precedência por campo, não média.** Média de magnitudes de duas redes
sismográficas não é uma magnitude — é um número que ninguém mediu. Cada campo
tem uma ordem de precedência de fonte declarada em configuração (USGS ganha em
epicentro e magnitude de sismo; GDACS ganha em exposição populacional; a agência
nacional ganha em geometria de área afetada).

**Divergência é produto, não ruído.** Todo valor de todas as fontes vai para
`event_field_claims`. O painel de procedência mostra a discordância
explicitamente — é a promessa central da interface. Esconder a divergência seria
repetir exatamente o problema que o produto existe para resolver.

`confianca` e `source_count` saem daqui. E vale a regra do score: nunca
aparecem sozinhos, sempre ao lado das métricas físicas que os originaram.

### 5.6 Caso especial: focos de calor

FIRMS entrega **pixels**, não eventos — potencialmente milhões de linhas, e um
único incêndio gera centenas de focos. Jogar isso direto no motor de correlação
estoura o banco e o clustering.

Tratamento: agregação espaço-temporal (DBSCAN via `ST_ClusterDBSCAN`) na
ingestão, transformando focos em um polígono de incêndio com área e contagem.
Só o agregado entra como `source_record`. Os pixels crus continuam em
`raw_payloads` — o ativo histórico é preservado sem poluir o modelo operacional.

Este é o item de maior risco técnico e de custo de armazenamento do plano.
Merece um spike próprio antes de entrar no cronograma da Fase 5.

### 5.7 Avaliação

Não se lança motor de dedup sem conjunto rotulado. O golden set nasce na Fase 2,
não no final: 300–500 pares rotulados à mão a partir de dados reais já
coletados, com viés deliberado para casos difíceis (sismos próximos no tempo,
enxames, ciclones com trajetórias vizinhas).

Métricas: precisão e recall par-a-par, mais métrica de cluster. **Precisão é a
que trava o portão** — ver G2.

## 6. Licenciamento como código

A pendência Copernicus/INMET não deve virar algo que alguém precise lembrar. Ela
entra como coluna `sources.redistribuicao`:

- `livre` — USGS, NOAA (domínio público dos EUA).
- `atribuicao` — NASA. Redistribuível com crédito; a atribuição exigida vai em
  `sources.atribuicao_exigida` e é renderizada automaticamente.
- `interna` — Copernicus, INMET **até haver resposta por escrito**. Fontes
  marcadas assim podem ser usadas para correlação, validação cruzada e cálculo
  de confiança, mas o serializador da API **remove o payload** dessas fontes da
  resposta. O evento canônico pode dizer "5 fontes confirmam"; não pode entregar
  o conteúdo da fonte restrita.

Isso implementa o plano B sem esperar a resposta jurídica, e faz o tier pago
ficar seguro por construção em vez de por disciplina. Teste automatizado: nenhum
`response_model` serializa campo originado de fonte `interna`.

## 7. Portões de decisão

Momentos em que o plano para e algo precisa ser verdade antes de continuar.

| | Quando | Critério | Se falhar |
|---|---|---|---|
| **G1** | Fim da Fase 0 | `payload_raw` gravando USGS em produção, com verificação de que não há lacuna | Nada mais começa. É o único item irrecuperável |
| **G2** | Fim da Fase 2 | Precisão par-a-par ≥ 0,95 e recall ≥ 0,80 no golden set, para terremotos | **Não avança para a interface.** Volta ao motor. Este é o "cortar em qualquer outra dimensão antes de cortar aqui" transformado em regra operacional |
| **G3** | Fim da Fase 4 | Decisão registrada: usuário gratuito primário é desenvolvedor ou organização | Não se investe em portal de API nem em motor de alertas antes disso. Construir os dois é a forma de não terminar nenhum |
| **G4** | Antes de qualquer tier pago | Resposta **por escrito** sobre Copernicus e INMET | Fontes permanecem `interna`. O tier pago sai só com USGS/NOAA/NASA |
| **G5** | Antes do lançamento | Fronteira do freemium publicada | Mudar depois queima confiança de forma desproporcional ao ganho |

## 8. Fases

Estimativas para execução solo em dedicação integral. São ordens de grandeza,
não compromissos — a sequência importa mais que as datas.

### Fase 0 — Coletar antes de tudo (semana 1)

Primeiro commit do repositório (hoje `main` está vazia), `compose.yaml` com
Postgres+PostGIS, Alembic migration 001 com `tenant_id` e RLS, tabelas
`sources`/`ingest_runs`/`raw_payloads` particionadas, e um coletor USGS que só
faz `GET` e grava o corpo. Sem parser. CI mínima.

→ **G1.** A partir daqui o ativo histórico está sendo formado.

### Fase 1 — Dois conectores e normalização (semanas 2–3)

USGS e GDACS: `fetch`/`parse` separados, parser rodando sobre `raw_payloads`
com replay idempotente, tratamento de revisão (nova versão = novo
`source_record`, nunca update), extração de `xrefs`, agendamento por fonte com
ETag/If-Modified-Since e backoff. View de saúde de fontes — que já tem tela
desenhada no protótipo.

### Fase 2 — O motor (semanas 4–6)

O coração. Blocking com parâmetros por tipo, cruzamento determinístico, features
e regressão logística, union-find com guarda de diâmetro, síntese canônica com
precedência por campo e `event_field_claims`. Golden set e harness de avaliação
em `eval/`. Escopo inicial: **terremotos apenas** — um tipo bem resolvido vale
mais que cinco pela metade.

→ **G2.** Portão duro.

### Fase 3 — API e tempo real (semanas 7–8)

REST de leitura sobre `v_eventos_atuais`, com filtros de bbox/tipo/severidade e
o endpoint de procedência de um evento. WebSocket com snapshot inicial +
deltas e *resume token* (`since_seq`), para que reconexão não perca eventos.
Tiles vetoriais via `ST_AsMVT` para a camada densa/histórica. Trava de
serialização por licença, com teste.

### Fase 4 — Front-end de produção (semanas 9–12)

Vite + React + TS. Tokens de design portados do protótipo (já são um sistema
coerente; não redesenhar). MapLibre GL com estilo que reproduz a estética
existente. As seis telas viram rotas de verdade, consumindo a API.

O **painel de procedência é tela nova** — não existe no protótipo e é a
interface do diferencial. Precisa mostrar, por campo, o que cada fonte afirma e
onde elas discordam. Merece o maior cuidado de design da fase.

→ **G3.** Decisão dev vs organização.

### Fase 5 — Ampliação de fontes (semanas 13–14)

NASA EONET (e seus cruzamentos gratuitos), NOAA/NWS CAP e NHC, FIRMS com o
clustering de §5.6. Copernicus e INMET entram como `interna`. Expansão do motor
para ciclone e enchente, cada tipo passando pelo mesmo critério de G2 antes de
ir ao ar.

### Fase 6 — Endurecimento e lançamento (semanas 15–16)

Observabilidade, alarme de fonte silenciosa, backup e teste de restauração,
rate limit, documentação pública do score como heurística de ordenação, e a
fronteira do freemium publicada.

→ **G4**, **G5**. Lançamento da v1 gratuita.

**Total: ~16 semanas.**

### Fora da v1, explicitamente

Relatórios com IA, alertas e webhooks, tier pago, exportação em massa, API
pública documentada, app móvel. Todos têm tela no protótipo e nenhum entra
antes de o motor estar sólido — a tela existir não é motivo para construir.

## 9. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Volume do FIRMS estoura banco e clustering | Custo e latência inviáveis | Agregação DBSCAN na ingestão; spike próprio antes da Fase 5 |
| Falso merge une eventos distintos | Perda de credibilidade — o oposto da promessa | Calibrar para precisão; encadeamento vai para revisão, não para merge |
| Motor escorrega para depois da interface | Produto vira clone de ferramenta gratuita | G2 é portão duro, não marco informativo |
| Fonte muda formato sem aviso | Parser quebra, ingestão para | `payload_raw` permite replay; alarme de parse-failure e de fonte silenciosa |
| Escopo de 16 semanas solo derrapa | Nada é lançado | Um tipo de evento por vez; o que sai primeiro são tipos e telas, nunca o motor |
| Licença bloqueia tier pago | Modelo de receita inviável nessas fontes | `redistribuicao='interna'` por padrão; G4 antes de cobrar |

## 10. Primeiros sete dias

Sequência concreta, na ordem:

1. `git init` já feito; primeiro commit com o protótipo, `CLAUDE.md` e este plano.
2. `compose.yaml`: Postgres 16 + PostGIS 3.4, volume persistente.
3. Alembic + migration 001: `tenants`, `sources`, `ingest_runs`, `raw_payloads`
   particionada, RLS ativa, `tenant_id` em tudo.
4. Conector USGS mínimo: `GET` do feed horário, gravação do corpo cru com
   `sha256`, `ingest_run` registrado.
5. Agendador ARQ de um job só, a cada 60 s.
6. Deploy no VPS. **Coleta começa aqui** — este é o dia que importa.
7. Verificação de continuidade: consulta que detecta lacuna de coleta acima de
   5 minutos, e alarme.

Só depois disso escrever o primeiro parser.
