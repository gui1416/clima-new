# web — front-end

React + TypeScript + Vite + MapLibre GL. Interface em pt-BR.

Estado: seis rotas sobre **dado real** da API de produto (`/api`). Quatro têm
dado que as sustente — visão geral, mapa, eventos e fontes; alertas e relatórios
continuam reservadas, e o texto de cada uma diz de que portão do
[plano](../docs/plano-de-construcao.md) elas dependem.

A gramática visual é a de `clima-global-prototipo-v2.html`: mesmo sprite de
ícones, mesmo cabeçalho de tela, mesma barra lateral, mesma paleta de comandos
(⌘K), mesmos flutuantes sobre o mapa. O que **não** foi portado do protótipo é
tudo que era dado inventado — o perfil de usuário na barra lateral virou o estado
real da coleta, e os selos de tendência ("+12% hoje") viraram razões entre números
que já estão na tela.

## Comandos

```bash
npm install
```

```bash
npm run dev
```

Abre em `http://localhost:5173`. `/saude` é proxiado para `localhost:8000` (a API
operacional do back-end).

```bash
npm run build
```

`npm run lint` roda só a checagem de tipos (`tsc --noEmit`).

```bash
npm run verificar
```

```bash
npm run verificar-responsivo
```

Abre a aplicação num Chromium headless e verifica que o mapa **de fato** renderiza,
salvando uma captura em `.artefatos/`. Precisa do servidor de desenvolvimento no ar
(`--tema=light` verifica o outro tema).

Isto não é luxo. Build limpo e tipos corretos **não provam que o mapa aparece** —
três defeitos passaram por `tsc` e pelo bundler e só apareceram no navegador:

| Defeito | Sintoma | Por que passou |
|---|---|---|
| `color-mix()` num `paint` do MapLibre | mapa não carrega, sem mensagem | o MapLibre tem parser de cor próprio e valida o estilo em runtime |
| `maxBounds` com longitude ±200 | zoom ~3,8 em vez de 1,1, marcadores todos fora da tela | longitude fora de ±180 é envolvida, virando faixa de 40° |
| `.marcador { position: relative }` | marcador *n* deslocado (n−1)×14px | mesma especificidade que `.maplibregl-marker`, e vence por ordem de importação |

O terceiro é o mais instrutivo: só o 18º marcador saía do canvas, então "18
marcadores no DOM" e uma captura plausível diziam que estava tudo bem enquanto 16
apontavam para o lugar errado. Daí a verificação comparar cada elemento com
`map.project()` em vez de só contar elementos.

`verificar-responsivo` abre as quatro rotas com dado em dez tamanhos de tela — de
320×568 a 2560×1440, incluindo o telefone deitado (812×375) — e falha se houver
rolagem horizontal, se o mapa ficar menor que 240×200, ou se algum alvo tiver menos
de 40 px em ponteiro grosso. Ele ignora o que é o desenho funcionando (marcador
fora do enquadramento, tabela dentro de `.tabela-rolagem`) verificando se algum
ancestral recorta o elemento.

Existe pela mesma razão que a verificação do mapa: responsividade não é
verificável por inspeção. O que quebra num layout fluido quase nunca aparece na
largura em que se está olhando — uma tabela de sete colunas empurra o `body` a
700 px e não a 1440; um piso de altura em `dvh` esmaga o mapa a 375 px de altura e
não a 900. As três telas que se costuma testar são justamente as três em que já
se olhou.

O script tem um marcapasso próprio: quarenta carregamentos de página passam das
120 requisições por minuto do limitador da API, e uma tela renderizada com 429
mede outra coisa. Ele conta as próprias requisições e espera caber na janela.

Se o Chromium reclamar de biblioteca faltando, o caminho limpo é
`sudo npx playwright install-deps`. Sem root, dá para extrair os `.deb` de
`libnspr4`, `libnss3` e `libasound2t64` em `.artefatos/libs` — o script detecta e
usa automaticamente.

## A geometria vem do protótipo, por script

`npm run dados` — roda automaticamente antes de `dev` e de `build` — extrai a
**geometria** de `clima-global-prototipo-v2.html` para `public/dados/`:

| Script | Saída | O que faz |
|---|---|---|
| `scripts/geometria-do-prototipo.mjs` | `paises.json` (187 KB) | Converte a geometria Natural Earth 1:50m de coordenadas projetadas para lat/lon |

Só a geometria. Os 18 eventos de demonstração do protótipo saíram quando o
back-end passou a entregar sismos reais — evento agora vem de `/api/eventos`, e
manter uma segunda fonte seria manter uma segunda verdade.

A saída **não é versionada**: é derivada, e o protótipo é a única fonte. Transcrever
à mão criaria uma cópia que envelhece sozinha.

### A conversão de geometria

O protótipo guarda os países como paths SVG **já projetados** — a projeção
equirretangular foi aplicada na geração. Mas a transformação é linear e conhecida,
portanto invertível:

```
projX(lon) = (lon + 180) * K       K = WORLD.w / 360
projY(lat) = (latTop - lat) * K
```

Então o mesmo dado 1:50m que já estava no repositório serve ao MapLibre sem baixar
nada. **O mapa é a tela principal do produto**: depender de tiles de terceiro nele
significaria chave de API, limite de requisição e uma conta a pagar por algo que já
temos.

Duas armadilhas resolvidas no script, ambas descobertas ao verificar a saída:

1. **Cópias deslocadas.** O gerador do protótipo emite duas cópias do que cruza o
   antimeridiano — o mesmo anel transladado 360°, para aparecer nas duas bordas de
   um mapa plano. A Rússia é o caso grande: 677 pontos duplicados, uma cópia em
   lon 27→190 e outra em -333→-170. O MapLibre já repete o mundo ao rolar; manter
   as duas desenharia a Rússia atravessada no Atlântico. O script agrupa anéis por
   assinatura (nº de pontos + faixa de latitude, que a translação não altera) e
   mantém o de maior sobreposição com [-180, 180].
2. **Fechamento de anel.** O `Z` do SVG fecha implicitamente; GeoJSON exige o
   ponto repetido.

Sobram 49 pontos além de ±180 — são as travessias legítimas do antimeridiano
(Chukotka, ilha de Wrangel), e o MapLibre as renderiza corretamente.

O dado para em **-57° de latitude**: a Antártida não está no protótipo. `maxBounds`
respeita esse recorte para não mostrar oceano vazio.

## Estrutura

```
src/
├─ estilos/tokens.css        cores do protótipo + escala fluida (clamp)
├─ estilos/base.css          shell, componentes, marcadores, camada responsiva
├─ tipos.ts                  espelha api/clima/api/esquemas.py
├─ formato.ts                pt-BR num lugar só: vírgula decimal, 24 h, fuso local
├─ tema.ts                   data-theme + localStorage, com barramento de inscrição
├─ dados/api.ts              cliente REST, hook de polling e o fluxo ao vivo
├─ dados/carregar.ts         busca a geometria em runtime
├─ componentes/Icones.tsx    sprite SVG portado do protótipo
├─ componentes/PaletaComandos.tsx  busca global (⌘K) sobre dado real
├─ componentes/ui/drawer.tsx gaveta do cartão de evento (Base UI)
├─ mapa/estilo.ts            estilo MapLibre montado em código, sem fonte externa
├─ mapa/MapaGlobal.tsx       mapa, flutuantes, filtros, faixa de eventos
├─ mapa/CartaoEvento.tsx     procedência campo a campo do evento selecionado
├─ rotas.tsx                 as seis telas
└─ App.tsx                   barra lateral, topo, roteamento, ⌘K
```

### Decisões que não são óbvias

- **Sem camada `symbol`, logo sem `glyphs`.** Rótulo de texto no MapLibre exige
  servidor de glifos. Marcadores são elementos DOM (`maplibregl.Marker`), o que
  mantém pulsação, foco de teclado e `aria-label` no CSS/HTML.
- **Tokens em CSS, lidos por JS.** O MapLibre não lê CSS, então `mapa/estilo.ts`
  lê as custom properties com `getComputedStyle` e remonta o estilo quando o tema
  muda (daí o barramento em `tema.ts`). Tema claro e escuro vivem em um lugar só.
- **Dados buscados, não importados.** `resolveJsonModule` num JSON de 187 KB faria
  o TypeScript inferir um tipo literal gigante a cada checagem, e o arquivo entraria
  no bundle principal. Buscar por rede é também o que continua valendo quando isso
  virar tile vetorial do PostGIS: só a URL muda.
- **MapLibre em chunk próprio.** São ~803 KB que praticamente nunca mudam, contra
  ~12 KB de aplicação que mudam a cada deploy. Separados, atualizar a aplicação não
  invalida o cache do mapa.

### Responsividade: a escala primeiro, o `@media` depois

A regra é que **tamanho** se resolve em `clamp()` nos tokens e **forma** se
resolve em `@media`. Espaço, tipografia, largura da barra lateral, altura do topo
e largura máxima da página são todos contínuos (`--e-1`…`--e-6`, `--t-micro`…
`--t-titulo`), então valem para qualquer largura em vez de para as três que foram
testadas. Sobra para os `@media` só o que de fato muda de arranjo: a barra lateral
vira gaveta em 900 px, a tabela de sete colunas vira cartão em 640 px, a coluna do
feed sai em 1180 px.

A versão anterior fazia o contrário — redefinia `font-size` e `padding` dentro de
três `@media` — e ficava correta em 640 e em 900 px e visivelmente errada em
700 px. Acima de 1480 px não havia nada, e a página parava de crescer.

Três decisões que não se veem no CSS:

- **Consultas de contêiner nos flutuantes do mapa.** Abas de estilo e leitura de
  coordenadas somem por `@container mapa (max-width: …)`, não por largura de
  janela. Num laptop de 1280 px com a barra de filtros aberta o mapa tem os mesmos
  ~900 px que teria num tablet sem barra, e é a largura do mapa que decide se as
  abas cabem.
- **Ponteiro grosso, não "celular".** Os alvos de 44 px vêm de
  `@media (pointer: coarse)`. Um laptop com tela sensível cai nessa regra e um
  celular ligado a um mouse não — é o ponteiro que define o alvo, não a largura.
  O marcador do mapa cresce como alvo sem crescer como desenho: o diâmetro visível
  codifica magnitude e não pode ser inflado, então a caixa vai a 40 px e os
  pseudoelementos passam a ser medidos a partir do centro.
- **A altura do mapa é o resto, com piso.** Era
  `calc(100dvh - 330px)` — a soma à mão das alturas do topo, do cabeçalho e da
  faixa. Bastava um título quebrar em duas linhas para o número mentir, e em janela
  baixa ele ficava negativo. Hoje é `minmax(clamp(280px, 46dvh, 560px), 1fr)`: o
  que não couber rola, em vez de esmagar o canvas. Pelo mesmo motivo o `minZoom`
  do MapLibre passou a ser medido em vez de fixo — `0.6` fixo abria o mapa num
  celular mostrando 40% do planeta, sem como afastar.

## O que falta

- Projeção: o protótipo é equirretangular, o MapLibre é Mercator. Diferença
  visível nas latitudes altas; decidir se vale customizar.
- Nenhum teste. A suíte do front entra junto com a API real, para não testar
  contra dado de demonstração que vai ser jogado fora.
- **Fila de revisão** (`/api/revisoes`) existe no back-end e não tem tela. Ela
  exige `X-API-Key` administrativa, então depende de decidir como a interface
  guarda credencial de operador.
- **Tiles vetoriais** (`/api/tiles/{z}/{x}/{y}.mvt`) existem e não são usados: com
  algumas centenas de eventos por janela, o GeoJSON de `/api/eventos` é menor que o
  custo de uma camada de tiles. Vale trocar quando a janela passar de alguns
  milhares.
- **`bbox` no servidor.** A faixa "eventos no enquadramento" recorta pelo limite do
  mapa no navegador, porque o dado já está lá. `bbox` só compensa quando o
  enquadramento passar a conter mais eventos do que cabe numa resposta.
