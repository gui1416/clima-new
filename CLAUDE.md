# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O produto

Plataforma geoespacial de monitoramento de eventos climáticos e desastres naturais.
Ingere fontes públicas (USGS, NOAA, NASA, Copernicus, INMET), normaliza,
**correlaciona registros que descrevem o mesmo evento do mundo real** e apresenta
num mapa interativo. Interface em **português do Brasil**.

A dor que o produto resolve não é "não existe mapa de desastres" — é "existem
cinco, e eles discordam entre si". O mesmo terremoto aparece no USGS, no GDACS e
num boletim da defesa civil com IDs, horários e magnitudes diferentes.

**O diferencial é o motor de correlação e deduplicação entre fontes.** É a única
parte que não é commodity. Sem ele, o produto é indistinguível de Zoom Earth,
Windy, GDACS, PDC Disaster Alert e NASA Worldview — todos gratuitos e mais
maduros. Decisão vinculante: a v1 entrega deduplicação entre **pelo menos duas
fontes**, mesmo que isso custe tipos de evento, camadas visuais ou features de
interface. Cortar escopo em qualquer outra dimensão é preferível a cortar aqui.

O que o produto **não** é: modelo de previsão (consolidamos observações, não
prevemos), fonte primária, ferramenta de despacho em campo, ou dashboard
meteorológico de uso geral (chuva de terça não é evento; enchente é).

## Estado atual do repositório

**Fases 0, 1, 2 e 3 construídas** ([plano](docs/plano-de-construcao.md)): o USGS é
coletado a cada 60 s, analisado para `source_records` append-only, correlacionado em
`canonical_events`, e servido em `/api/eventos`.

**Mas o motor de correlação não tem o que deduplicar: existe uma fonte só.** O feed
do USGS entrega eventos já mesclados, então hoje cada `source_record` vira um evento
canônico de uma fonte. O motor está exercitado por testes (inclusive recusando dois
sismos reais a 0,5 km e 62 s de distância), e o portão **G2 não está atendido** —
exige positivo real de uma segunda fonte. `api/eval/avaliar_g2.py` mede e explica
por quê.

Toda resposta de lista carrega `deduplicado: false` e `fontes_confirmando: 1`. Não
remova esses avisos antes de haver segunda fonte: são o que impede o produto de
afirmar consolidação que não houve.

A API de produto fica sob **`/api`**. Sem o prefixo ela colide com as rotas do SPA
(`/eventos`, `/fontes`) e o navegador recebe JSON em vez da aplicação.

Uma pasta por superfície, sempre. Nada de back-end fora de `/api`.

| Caminho | O que é |
|---|---|
| [api/](api/) | Back-end inteiro: FastAPI, conectores, ingestão, workers, migrations |
| [web/](web/) | Front-end web: React + TS + Vite + MapLibre GL. Mapa, painéis, eventos e fontes sobre dado real |
| [mobile/](mobile/) | App móvel. Fora da v1; o lugar está reservado |
| [docs/](docs/) | Plano de construção |
| [clima-global-prototipo-v2.html](clima-global-prototipo-v2.html) | Protótipo, congelado |

O protótipo é um arquivo único autocontido — 1.520 linhas, ~296 KB, 6 rotas, 18
eventos de demonstração, geometria Natural Earth 1:50m, nenhum `fetch`, nenhum
CDN. **Serve como especificação visual executável, não como base de código de
produção.** Ao construir o produto real, trate-o como referência de design a ser
reimplementada, não como código a ser estendido.

## Comandos

Back-end (detalhes em [api/README.md](api/README.md)):

```bash
cp .env.example .env && cp api/.env.example api/.env
```

Ajuste a senha nos dois arquivos — precisa ser a mesma — e o e-mail em
`USER_AGENT`. Depois:

```bash
docker compose up -d --build
```

Verificar integridade da coleta (200 = íntegra, 503 = lacuna, fonte silenciosa,
partição DEFAULT ocupada ou fila de análise parada):

```bash
curl -s localhost:8000/saude | python3 -m json.tool
```

```bash
curl -s "localhost:8000/api/eventos?horas=24" | python3 -m json.tool
```

Suíte completa em Docker (Postgres+PostGIS em tmpfs, descartável, não toca o
banco de desenvolvimento):

```bash
./scripts/testar.sh
```

Só os unitários, sem infraestrutura, de dentro de `api/`:

```bash
pytest --ignore=tests/integracao
```

```bash
ruff check clima && mypy clima
```

Um teste só: `./scripts/testar.sh -k test_papel_app_nao_ignora_rls`

Revisar o SQL de uma migration sem banco: `alembic upgrade head --sql`

Front-end (detalhes em [web/README.md](web/README.md)), de dentro de `web/`:

```bash
npm install && npm run dev
```

```bash
npm run build
```

`npm run dados` regenera a geometria e os eventos a partir do protótipo — roda
sozinho antes de `dev` e `build`, e as saídas em `web/public/dados/` não são
versionadas porque são derivadas.

Protótipo: `python3 -m http.server 8000`, depois abrir
`http://localhost:8000/clima-global-prototipo-v2.html`.

### Três armadilhas do back-end

Onde um erro causa dano silencioso em vez de exceção. Detalhes em
[api/README.md](api/README.md).

1. **RLS é forçada e fail-closed, e só funciona com papel não-superusuário.**
   Sessão sem `clima.tenant_id` definido não vê linha nenhuma — parece banco
   vazio, não erro de permissão; toda leitura e escrita passa por
   `clima.db.sessao()`. E a aplicação **precisa** conectar como `clima_app`
   (`DATABASE_URL`), nunca como o dono: superusuário ignora RLS por completo e o
   isolamento entre tenants deixa de existir sem nenhum sintoma.
2. **Não rode `alembic revision --autogenerate` contra `raw_payloads` ou
   `payload_bodies`.** Particionamento, RLS e partição DEFAULT não são
   representáveis nos modelos; o diff tentaria removê-los. `migrations/env.py`
   filtra essas tabelas, mas não conte com isso.
3. **Nunca `UPDATE` nem `DELETE` em `raw_payloads`/`payload_bodies`/`source_records`.**
   `ingest_runs` é exceção declarada (log operacional, aberto antes do fetch e
   fechado depois) e `parse_runs` também — apagar linha dela é o mecanismo de
   replay do parser.
4. **`analisar()` nunca toca a rede.** O parser lê de `payload_bodies` e é função
   pura. É o que faz bug de parser virar replay em vez de perda de dado, e o que
   permite testá-lo contra payload real gravado.
5. **A identidade de um evento canônico vem dos membros, não de `cluster_key`.**
   `cluster_key` é rótulo. Resolver identidade por chave derivada fazia o evento
   trocar de id quando entrava membro de outra fonte, orfanando o histórico — ver
   `motor._resolver_evento`. Evento absorvido numa fusão nunca é apagado: ganha
   `fundido_em` e sai da view de estado atual.

## Arquitetura do protótipo

Arquivo único, quatro regiões:

| Linhas | Conteúdo |
|---|---|
| 8–99 | CSS do shell: tokens de tema, reset, layout, responsividade |
| 100–347 | CSS do componente GeoMap (estilo shadcn/ui), tokens próprios |
| 350–517 | Markup: sprite SVG de ícones, sidebar, topbar, 6 views, overlays |
| 518–1517 | JS: dados mock, shell/SPA, blob de geometria, motor do mapa, estado de filtros |

### Dados mock

`EVENTS` ([:520](clima-global-prototipo-v2.html:520)) — 18 objetos, a única fonte
de dados. Campos por evento: `id`, `title`, `place`, `country`, `countryId`,
`region`, `type`, `severity`/`severityLabel`, `time`, `lat`/`lon`, `people`
(string formatada) e `exposure` (número em milhares), `sources`, `confidence`,
`metric`/`metricLabel`, `summary`, `sourceNames[]`, `updates[]`, `times[]`.

- `countryId` é **ISO 3166-1 numérico como string** (`'076'` Brasil, `'392'`
  Japão) — a chave que liga evento a país na geometria.
- `severity` ∈ `critical | high | moderate`; `type` ∈ `Terremoto | Ciclone |
  Incêndio | Enchente | Vulcão`. Ambos os vocabulários aparecem em CSS
  (`.severity-*`), filtros e ícones — mudar um exige varrer os três.
- `metric`/`metricLabel` existem porque o score composto **nunca** aparece
  sozinho (ver "Score" abaixo). Todo card, tooltip e drawer mostra a métrica
  física ao lado da severidade.
- Números vêm pré-formatados em pt-BR (vírgula decimal, `1,8 mi`). `updateStats`
  ([:584](clima-global-prototipo-v2.html:584)) deriva os totais de `exposure`.

### Shell / navegação SPA

`ROUTES` ([:540](clima-global-prototipo-v2.html:540)) mapeia slug → rótulo:
`overview`, `map`, `events`, `reports`, `alerts`, `sources`. `navigate(route)`
([:559](clima-global-prototipo-v2.html:559)) alterna `.active` entre `#view-<slug>`
e os botões `[data-route]`, atualiza breadcrumb e `document.title`.

Overlays compartilham um scrim: `openLayer`/`closeLayers`
([:564](clima-global-prototipo-v2.html:564)) controlam drawer de detalhes,
command palette (`Cmd/Ctrl+K`) e modais. `Escape` fecha tudo.

Tema: atributo `data-theme` em `<html>` (`dark` por padrão), persistido em
`localStorage['clima-theme']`. Toda cor vem de custom property — não escreva
valor de cor literal em regra nova.

### Geometria do mundo

`WORLD` ([:595](clima-global-prototipo-v2.html:595)) é uma **única linha de
135 KB**. Estrutura:

```js
{ w: 1000.0, h: 391.7, latTop: 84.0, latBottom: -57.0,
  countries: [{ i: '716', n: 'Zimbábue', b: [x0,y0,x1,y1], d: 'M586.9 295.6 …Z' }] }
```

`d` e `b` já estão em **coordenadas projetadas**, não em lat/lon — a projeção
equirretangular foi aplicada na geração. `GEO_K = w/360`; `projX(lon)`,
`projY(lat)` e as inversas `lonAt`/`latAt` ([:604–608](clima-global-prototipo-v2.html:604))
convertem entre lat/lon e esse espaço. Trocar de projeção significa regerar o
blob, não mudar as funções. `latBottom: -57` recorta a Antártida.

Cuidado ao editar: nunca reformate nem passe essa linha por prettificador — o
diff fica ilegível e o arquivo dobra de tamanho. Edite `WORLD` só regerando-o.

### Motor do mapa (`createGeoMap`)

`createGeoMap(root, { compact })` ([:624](clima-global-prototipo-v2.html:624)) é
uma **factory de closure** — sem framework, sem classes. Cada instância mantém
estado local em `S` (`k`, `tx`, `ty` da viewport, `tool`, `base`, `area`,
`layers`) e injeta sua própria árvore SVG + UI flutuante via template string.
IDs de `<pattern>` recebem sufixo `uid` (`dots-g1`) para que duas instâncias
coexistam sem colidir.

Duas instâncias são criadas na inicialização a partir de `[data-geomap]`
([:1494](clima-global-prototipo-v2.html:1494)): a `compact` na visão geral (sem
busca, sem abas de estilo, sem popover de camadas; roda do mouse só aproxima com
`Ctrl`) e a `full` na rota do mapa.

Camadas SVG em ordem: `geo-graticule` → `geo-zoom` (sombras + países, transformado
por pan/zoom) → `geo-screen` (halos, rótulos, marcadores, redesenhados em
coordenadas de tela) → retângulo de seleção. Marcadores e halos vivem em espaço
de tela para não escalarem com o zoom.

API pública devolvida ([:1372](clima-global-prototipo-v2.html:1372)) — o único
contrato entre shell e mapa:

`refresh()`, `fit(animate)`, `showCard(e)`, `hideCard()`, `focusEvent(e)`,
`highlightCountry(id)`, `inView()`, `setTool('pan'|'select')`, além de `root` e
`compact`.

Interação: arrastar para pan, roda/duplo clique/`+`/`-`/`0` para zoom, setas para
deslocar, `Shift`+arrastar (ou ferramenta de área) para seleção retangular,
clique em país filtra e enquadra, `Escape` limpa. Clustering, halos, grade e
rótulos são camadas ligáveis. Respeita `prefers-reduced-motion` via
`reduceMotion` ([:610](clima-global-prototipo-v2.html:610)).

### Estado de filtros compartilhado

Vive em escopo de módulo, fora das instâncias
([:1402–1492](clima-global-prototipo-v2.html:1402)): `hiddenSeverities` (Set),
`activeTypes` (Set), `mapCountry` (ISO numérico ou `null`), `selectedEvent`,
`mapSeverity`.

O fluxo é sempre o mesmo: **mutar o estado de módulo → chamar `renderMarkers()`**,
que faz `geoMaps.forEach(m => m.refresh())`, recalcula contadores e redesenha a
faixa de eventos. `visibleEvents()` ([:1425](clima-global-prototipo-v2.html:1425))
é o predicado único de filtragem (severidade + tipo + país + termo de busca) —
qualquer view nova deve consumi-lo em vez de refiltrar `EVENTS` por conta própria.

### Convenções

- Todo texto de UI em pt-BR, inclusive `aria-label` e comentários.
- Ícones só do sprite SVG em [:351](clima-global-prototipo-v2.html:351), via o
  helper `icon(name, cls)`; adicione um `<symbol id="i-*">` antes de usar.
- Elementos são endereçados por `data-*` (`data-route`, `data-geomap`,
  `data-sev`, `data-stat`, `data-count-type`), não por classe de estilo.
- Rótulos de acessibilidade e `role` já estão aplicados nos controles do mapa
  (`role="application"`, `combobox`, `switch`, `tablist`) — preserve ao editar.
- Dados falsos são declarados como falsos: exportações carregam `mockData:true`
  e os textos dizem "demonstração"/"simulado". Mantenha isso.
- Há um `'15 AGO 2026'` fixo em `updateClock`
  ([:593](clima-global-prototipo-v2.html:593)) — data de demo, não bug a corrigir
  em silêncio.

## Princípios de engenharia inegociáveis (back-end futuro)

Já decididos. Custam caro se descobertos tarde; não reabra sem motivo forte.

1. **`payload_raw` desde o primeiro evento ingerido.** Corpo bruto de cada
   resposta de cada fonte, imutável, com timestamp de coleta. Dado histórico não
   é reconstruível retroativamente — o que não for coletado hoje está perdido
   para sempre. É o ativo de longo prazo e a base de qualquer correlação,
   backtesting ou treino de modelo futuro.
2. **Append-only com snapshots.** Eventos mudam (magnitude revisada, área
   ampliada, alerta cancelado). Nunca sobrescrever: cada atualização é um novo
   snapshot; o estado atual é uma view sobre o último, não uma linha mutável.
3. **`tenant_id` na migration 001.** Mesmo com um único cliente, mesmo parecendo
   overkill. Retrofitar multi-tenancy em base com dados reais é reescrita.
4. **PostGIS como fonte de verdade geoespacial.** Geometria no banco, não em
   JSON. Índices espaciais desde o começo — a correlação depende de consultas de
   proximidade.
5. **Métricas componentes acima de score composto.** Ver abaixo.

### Score (0–10)

Comparar um terremoto M 6,4 com uma enchente de 186 mm/24h na mesma escala exige
uma função de equivalência sem fundamento científico — as grandezas não são
comensuráveis e qualquer peso é arbitrário. Portanto: o score existe como
recurso de **ordenação e triagem visual**; **nunca** aparece sozinho, sempre com
as métricas que o originaram; a documentação pública precisa dizer que é
heurístico de ordenação, não medida física; e o produto não afirma comparações
entre categorias ("este terremoto é mais grave que aquela enchente").

## Bloqueios e decisões pendentes

- **Licenciamento Copernicus e INMET.** Ambos têm termos que podem impedir
  revenda do dado via API paga. Resolver **antes** de construir qualquer tier
  pago que exponha essas fontes. Plano B: usá-las apenas para enriquecimento
  interno (correlação, validação cruzada) sem redistribuir o payload. USGS, NOAA
  e NASA são domínio público — livres, inclusive comercialmente (verificar
  atribuição exigida pela NASA).
- **Quem é o usuário gratuito primário.** Bloqueia o design. Se
  desenvolvedores: tier grátis precisa de docs de API, chaves e rate limit
  generoso — o produto vira infraestrutura. Se organizações (agro, seguros,
  defesa civil): precisa de alertas simples e relatório exportável — o produto
  vira ferramenta. Roadmaps diferentes; escolher uma.
- **Fronteira do freemium.** v1 é gratuita, mas a fronteira precisa ser definida
  e comunicada publicamente **antes** do lançamento — mudar depois queima
  confiança de forma desproporcional ao ganho. Proposta a confirmar: grátis =
  mapa em tempo real, busca/filtros, evento individual, 7 dias de histórico;
  pago = histórico além de 7 dias, alertas e webhooks, API, exportação em massa.
