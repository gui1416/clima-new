# Clima Global

Plataforma geoespacial de monitoramento de eventos climáticos e desastres naturais.
Ingere fontes públicas, normaliza, **correlaciona registros que descrevem o mesmo
evento do mundo real** e apresenta num mapa interativo. Interface em português do
Brasil.

## O problema

Já existem vários mapas de desastre — Zoom Earth, Windy, GDACS, PDC Disaster Alert,
NASA Worldview. Todos gratuitos, todos mais maduros. A dor não é falta de mapa.

A dor é que **as fontes discordam entre si**. O mesmo terremoto aparece no USGS, no
EMSC e num boletim da defesa civil com identificadores, horários e magnitudes
diferentes. Quem precisa agir — seguradora, cooperativa agrícola, defesa civil,
operador logístico — gasta o tempo de resposta reconciliando fontes em vez de decidir.

O diferencial deste projeto é o motor de correlação e deduplicação entre fontes. É a
única parte que não é commodity, e é a razão de o produto existir.

## Estado real

Honestidade sobre o estado é uma decisão de projeto aqui, não modéstia: a interface
carrega os avisos correspondentes e a API os devolve em toda resposta.

| Parte | Estado |
|---|---|
| Coleta de `payload_raw` | **funcionando** — USGS/EMSC a cada 60 s; GDACS a cada 15 min |
| Parser → observações normalizadas | **funcionando** — append-only, com replay |
| Motor de correlação | **construído e exercitado**, ver ressalva abaixo |
| API de leitura | **funcionando** — `/api/eventos`, `/api/estatisticas` |
| Interface web | **funcionando** — mapa, painéis, eventos, fontes, procedência |
| Alertas, webhooks, relatórios | **não construídos**, de propósito |
| Aplicativo móvel | fora da v1; a pasta está reservada |

### A ressalva que importa

O motor está pronto, testado e rodando — mas **quase não tem o que deduplicar
ainda**, e o motivo é de dados, não de código.

Medido em execução real: os catálogos do USGS e do EMSC só se sobrepõem de forma
consistente na faixa global de **M ≳ 4,5**. O GDACS agora acrescenta uma terceira
fonte para sismos significativos e carrega o identificador NEIC/USGS, permitindo
vínculo determinístico e a construção de verdade-base real.

Consequência: o portão de qualidade **G2** (precisão ≥ 0,95, recall ≥ 0,80) **não
está atendido**, por duas razões independentes — não há positivo real suficiente, e a
amostra de negativos reais é pequena. `api/eval/avaliar_g2.py` mede, explica e se
**recusa** a declarar aprovação com amostra insuficiente.

O que está provado: contra dado real, o motor recusou dois sismos genuinamente
distintos a **0,5 km e 62 s** de distância — dentro da janela de blocking, onde um
motor ingênuo os fundiria.

## Como rodar

Precisa de Docker e Node. O back-end sobe em contêiner; o front roda no host.

```bash
cp .env.example .env && cp api/.env.example api/.env
```

Ajuste as duas senhas (têm de bater entre os arquivos) e o e-mail em `USER_AGENT` —
várias fontes públicas pedem contato identificável.

```bash
docker compose up -d --build
```

```bash
cd web && npm install && npm run dev
```

Interface em `http://localhost:5173`. API em `http://localhost:8000`
(documentação interativa em `/docs`).

Integridade da coleta — 200 se íntegra, 503 se há lacuna, fonte silenciosa, partição
DEFAULT ocupada ou fila de análise parada:

```bash
curl -s localhost:8000/saude | python3 -m json.tool
```

### Testes

Suíte completa em Docker: Postgres+PostGIS em tmpfs, descartável, não toca o banco de
desenvolvimento.

```bash
./scripts/testar.sh
```

Só os unitários, sem infraestrutura nenhuma (de dentro de `api/`):

```bash
pytest --ignore=tests/integracao
```

O mapa renderizando de fato, num Chromium headless (de dentro de `web/`) — build
limpo e tipos corretos não provam que a tela funciona:

```bash
npm run verificar
```

## Estrutura

Uma pasta por superfície, sempre. Nada de back-end fora de `/api`.

| Caminho | O que é |
|---|---|
| [api/](api/) | Back-end inteiro: FastAPI, conectores, motor de correlação, workers, migrations |
| [web/](web/) | Front-end: React + TypeScript + Vite + MapLibre GL |
| [mobile/](mobile/) | Aplicativo móvel. Reservado, fora da v1 |
| [docs/](docs/) | [Plano de construção](docs/plano-de-construcao.md): arquitetura, esquema, portões |
| [clima-global-prototipo-v2.html](clima-global-prototipo-v2.html) | Protótipo congelado — especificação visual, não código de produção |

Como o dado atravessa:

```
conectores ──► raw_payloads ──► source_records ──► canonical_events ──► /api ──► web
   (rede)      (imutável)       (append-only)      (correlacionado)
                    │
                    └── replay: parser lê do bruto, nunca da rede
```

## Fontes de dados

Todas gratuitas para acessar. **Gratuito e redistribuível são coisas diferentes**, e
essa diferença é coluna no banco (`sources.redistribuicao`), não anotação: fonte
restrita participa da correlação e do cálculo de confiança, e o serializador remove o
conteúdo dela da resposta da API.

| Fonte | Estado | Redistribuição |
|---|---|---|
| USGS | coletando | livre — domínio público dos EUA |
| EMSC | coletando | atribuição — **confirmar** termos comerciais |
| GDACS | coletando | atribuição — **confirmar** termos comerciais |
| NOAA / NWS | catalogada | livre — domínio público |
| NASA EONET, FIRMS | catalogadas | atribuição |
| Copernicus EMS, INMET | catalogadas | **uso interno** — bloqueio jurídico pendente |

O portão **G4** impede qualquer tier pago que exponha fonte não confirmada.

## Decisões que não se reabrem sem motivo forte

Custam caro se descobertas tarde. O racional completo está em
[CLAUDE.md](CLAUDE.md) e no [plano](docs/plano-de-construcao.md).

1. **`payload_raw` desde o primeiro evento.** Dado histórico não é reconstruível
   retroativamente. O que não for coletado hoje está perdido para sempre.
2. **Append-only com snapshots.** Magnitude revisada gera linha nova; o estado atual
   é uma view sobre a última, nunca uma linha mutável.
3. **`tenant_id` desde a migration 001**, com RLS forçada e fail-closed.
4. **PostGIS como fonte de verdade geoespacial.** A correlação depende de consultas
   de proximidade com índice.
5. **Métricas componentes acima de score composto.** Severidade nunca aparece sem a
   grandeza física que a originou — é contrato do schema da API, não convenção.
6. **Precedência por campo, nunca média.** A média das magnitudes de duas redes
   sismográficas não é uma magnitude: é um número que ninguém mediu.
7. **Falso merge é pior que falso split.** Unir eventos distintos esconde um evento
   real; duplicatas apenas repetem informação. Daí três vereditos em vez de dois, com
   fila de revisão para a dúvida.

## O que vem a seguir

1. **Deploy.** A coleta roda num laptop, e é o único item irrecuperável do projeto —
   G2 depende de dias de coleta contínua. Falta também o serviço do front no compose.
2. **Interface da fila de revisão.** Decisão humana registrada é a única verdade-base
   real que o sistema acumula, e o que tornaria o recall de G2 mensurável sem
   perturbação sintética.
3. **Portão G3:** quem é o usuário gratuito primário — desenvolvedor (o produto vira
   infraestrutura) ou organização (vira ferramenta). Roadmaps diferentes.
