# web — front-end

React + TypeScript + Vite + MapLibre GL. Interface em pt-BR.

Estado: shell navegável com mapa mundial funcional sobre **dados de
demonstração**. A API de produto não existe ainda (Fase 3 do
[plano](../docs/plano-de-construcao.md)), então só duas das seis telas têm dado
que as sustente; as outras quatro são espaço reservado que diz o que falta.

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

Se o Chromium reclamar de biblioteca faltando, o caminho limpo é
`sudo npx playwright install-deps`. Sem root, dá para extrair os `.deb` de
`libnspr4`, `libnss3` e `libasound2t64` em `.artefatos/libs` — o script detecta e
usa automaticamente.

## Os dados vêm do protótipo, por script

`npm run dados` — roda automaticamente antes de `dev` e de `build` — extrai duas
coisas de `clima-global-prototipo-v2.html` para `public/dados/`:

| Script | Saída | O que faz |
|---|---|---|
| `scripts/geometria-do-prototipo.mjs` | `paises.json` (187 KB) | Converte a geometria Natural Earth 1:50m de coordenadas projetadas para lat/lon |
| `scripts/eventos-do-prototipo.mjs` | `eventos-demo.json` | Extrai os 18 eventos de demonstração |

As saídas **não são versionadas**: são derivadas, e o protótipo é a única fonte de
verdade. Transcrever à mão criaria uma segunda.

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
├─ estilos/tokens.css   tokens portados do protótipo — não redesenhar
├─ estilos/base.css     layout, componentes, marcadores
├─ tipos.ts             Evento, Severidade. NÃO é o contrato final
├─ tema.ts              data-theme + localStorage, com barramento de inscrição
├─ dados/carregar.ts    busca os assets em runtime
├─ mapa/estilo.ts       estilo MapLibre montado em código, sem fonte externa
├─ mapa/MapaGlobal.tsx  mapa, marcadores, legenda, cartão do evento
├─ rotas.tsx            as seis rotas
└─ App.tsx              sidebar, topbar, roteamento
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

## O que falta

- Projeção: o protótipo é equirretangular, o MapLibre é Mercator. Diferença
  visível nas latitudes altas; decidir se vale customizar.
- Nenhum teste. A suíte do front entra junto com a API real, para não testar
  contra dado de demonstração que vai ser jogado fora.
- **Painel de procedência** (`/procedencia`) é a tela do diferencial e não existe
  no protótipo. Depende de `event_field_claims` — Fase 2.
