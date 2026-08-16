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

Um único arquivo: [clima-global-prototipo-v2.html](clima-global-prototipo-v2.html)
— protótipo navegável de alta fidelidade, 1.520 linhas, ~296 KB, 6 rotas, 18
eventos de demonstração com coordenadas reais e geometria Natural Earth 1:50m.

Sem back-end, sem build, sem dependências, sem `package.json`, sem testes, sem
commits ainda (`main` está vazia). O arquivo é autocontido: nenhum `fetch`,
nenhum CDN, nenhuma fonte externa — abre direto via `file://`.

**Serve como especificação visual executável, não como base de código de
produção.** Ao construir o produto real, trate-o como referência de design e
comportamento a ser reimplementado, não como código a ser estendido.

O caminho até o produto está em
[docs/plano-de-construcao.md](docs/plano-de-construcao.md) — arquitetura,
esquema do banco, desenho do motor de correlação, portões de decisão e
faseamento. Stack travada: Python + FastAPI, PostgreSQL/PostGIS, ARQ,
React + TypeScript + MapLibre GL.

## Comandos

Não há toolchain. Para ver o protótipo:

```bash
python3 -m http.server 8000
```

Depois abra `http://localhost:8000/clima-global-prototipo-v2.html`. Abrir o
arquivo direto no navegador também funciona.

Ao introduzir back-end ou build, adicione os comandos aqui.

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
