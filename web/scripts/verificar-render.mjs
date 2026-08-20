/**
 * Abre a aplicação num Chromium headless e verifica que o mapa **de fato**
 * renderiza. Build limpo e tipos corretos não provam isso: um `color-mix()` num
 * paint do MapLibre passa por tsc e pelo bundler, e derruba o mapa em tempo de
 * execução — foi exatamente o que aconteceu.
 *
 * Verifica, em ordem de gravidade:
 *   1. nenhum erro de console e nenhuma exceção de página;
 *   2. o canvas WebGL do MapLibre existe e tem área;
 *   3. há marcador no DOM (prova que o `load` chegou e a API respondeu);
 *   4. **os marcadores estão na posição que o mapa projeta** — presença no DOM
 *      não é visibilidade nem posição certa. Um `maxBounds` inválido já jogou todos
 *      fora da tela, e um `position: relative` já deslocou cada um por (n−1)×14px;
 *   5. o canvas não está em branco, medido pelo tamanho do PNG: uma imagem de cor
 *      única comprime para poucos KB. (Ler `readPixels` não serve — o MapLibre usa
 *      `preserveDrawingBuffer: false` e o buffer está vazio fora do frame.)
 *
 * Uso: node scripts/verificar-render.mjs [url] [--tema=dark|light]
 */

import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));

// `npx playwright install-deps` precisa de root. Onde não houver, as bibliotecas
// que o Chromium headless exige (libnspr4, libnss3, libasound2) podem ser
// extraídas de .deb para .artefatos/libs sem tocar no sistema. Precisa estar no
// ambiente ANTES de lançar o navegador, porque o filho é que faz o dlopen.
const LIBS = resolve(AQUI, "../../.artefatos/libs/root/usr/lib/x86_64-linux-gnu");
if (existsSync(LIBS)) {
  process.env.LD_LIBRARY_PATH = [LIBS, process.env.LD_LIBRARY_PATH]
    .filter(Boolean)
    .join(":");
}

const { chromium } = await import("playwright");

const URL_BASE = process.argv[2]?.startsWith("http") ? process.argv[2] : "http://localhost:5173";
const TEMA = (process.argv.find((a) => a.startsWith("--tema=")) ?? "--tema=dark").split("=")[1];
const SAIDA = resolve(AQUI, `../../.artefatos/mapa-${TEMA}.png`);

const problemas = [];
const navegador = await chromium.launch();
const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 } });

// `/saude` responde 503 de propósito quando há lacuna de coleta, e o Chromium
// registra toda resposta de erro no console. É estado esperado do produto, não
// falha de renderização — e a interface trata o 503 lendo o corpo. Sem este
// filtro, a verificação do mapa passaria a falhar sempre que a coleta tivesse
// uma lacuna, que é justamente quando ela precisa continuar utilizável.
const RUIDO_ESPERADO = [/Failed to load resource.*503/i];

pagina.on("console", (m) => {
  if (m.type() !== "error") return;
  const texto = m.text();
  if (RUIDO_ESPERADO.some((r) => r.test(texto))) return;
  problemas.push(`console: ${texto}`);
});
pagina.on("pageerror", (e) => problemas.push(`exceção: ${e.message}`));

await pagina.goto(`${URL_BASE}/mapa`, { waitUntil: "networkidle" });
if (TEMA === "light") {
  await pagina.click('button[aria-label="Usar tema claro"]');
}

// O `load` do MapLibre é assíncrono; os marcadores só existem depois dele.
let marcadores = 0;
try {
  await pagina.waitForSelector(".marcador", { timeout: 20000 });
  marcadores = await pagina.locator(".marcador").count();
} catch {
  problemas.push(
    "nenhum marcador apareceu em 20 s — o mapa não carregou, ou a API não devolveu sismo " +
      "na janela de 24 h (verifique se o back-end está no ar)",
  );
}

const painelDeErro = await pagina.locator(".vazio h2").count();
if (painelDeErro) {
  problemas.push(`a aplicação mostrou erro: ${await pagina.locator(".vazio p").first().innerText()}`);
}

const canvas = await pagina.evaluate(() => {
  const c = document.querySelector(".mapa-canvas canvas");
  if (!c) return null;
  const r = c.getBoundingClientRect();
  return { largura: Math.round(r.width), altura: Math.round(r.height) };
});
if (!canvas) problemas.push("canvas do MapLibre não existe no DOM");
else if (canvas.largura < 200 || canvas.altura < 200)
  problemas.push(`canvas com área insuficiente: ${canvas.largura}x${canvas.altura}`);

// Marcador no DOM não é marcador no lugar certo. A checagem forte compara a
// posição real de cada elemento com a projeção que o próprio mapa calcula: foi
// assim que apareceu um `position: relative` jogando os marcadores no fluxo
// normal, com erro de (n−1)×14px. Só o 18º saía do canvas; os outros 16 erravam
// em silêncio sobre um mapa que parecia plausível.
const TOLERANCIA_PX = 2;
const posicoes = await pagina.evaluate(async (tol) => {
  const mapa = window.__mapa;
  if (!mapa) return { semMapa: true };

  const c = document.querySelector(".mapa-canvas canvas");
  const r = c.getBoundingClientRect();
  // Compara contra a MESMA fonte que a aplicação usa: a API.
  const evts = (await (await fetch("/api/eventos?horas=24&magnitude_minima=2.5&limite=500")).json())
    .itens;
  // Casa por id, não por título: numa sequência de tremores secundários vários
  // eventos têm título idêntico, e casar por texto compararia marcador de um com
  // coordenada de outro — produzindo desvio falso de poucos pixels.
  const porId = new Map(evts.map((e) => [e.id, e]));

  let dentro = 0;
  const desviados = [];
  const rotulosGenericos = [];

  for (const el of document.querySelectorAll(".marcador")) {
    const b = el.getBoundingClientRect();
    const cx = b.x + b.width / 2;
    const cy = b.y + b.height / 2;
    if (cx >= r.x && cx <= r.x + r.width && cy >= r.y && cy <= r.y + r.height) dentro++;

    if (/^Map marker$/i.test(el.getAttribute("aria-label") ?? "")) {
      rotulosGenericos.push(el.title);
    }

    const e = porId.get(el.dataset.id);
    if (!e) continue;
    const p = mapa.project([e.lon, e.lat]);
    const dx = Math.abs(cx - r.x - p.x);
    const dy = Math.abs(cy - r.y - p.y);
    if (dx > tol || dy > tol) {
      desviados.push({ lugar: e.lugar, dx: Math.round(dx), dy: Math.round(dy) });
    }
  }
  return { dentro, desviados, rotulosGenericos };
}, TOLERANCIA_PX);

if (posicoes.semMapa) {
  problemas.push("window.__mapa ausente — rode contra o servidor de desenvolvimento");
}
const dentro = posicoes.dentro ?? 0;
for (const d of posicoes.desviados ?? []) {
  problemas.push(`marcador fora da projeção: ${d.lugar} desviado ${d.dx}x${d.dy}px`);
}
if (posicoes.rotulosGenericos?.length) {
  problemas.push(
    `${posicoes.rotulosGenericos.length} marcadores com aria-label "Map marker" — ` +
      "o MapLibre sobrescreveu o rótulo em pt-BR",
  );
}

// Um PNG de cor única comprime para quase nada; um mundo com 178 países, não.
const LIMITE_BRANCO_KB = 20;
const pngMapa = await pagina.locator(".mapa-canvas").screenshot();
const kbMapa = pngMapa.length / 1024;
if (kbMapa < LIMITE_BRANCO_KB) {
  problemas.push(
    `canvas parece em branco: PNG de ${kbMapa.toFixed(1)} KB (< ${LIMITE_BRANCO_KB} KB)`,
  );
}

mkdirSync(dirname(SAIDA), { recursive: true });
await pagina.screenshot({ path: SAIDA });
await navegador.close();

console.log(`tema:       ${TEMA}`);
console.log(`marcadores: ${marcadores} no DOM, ${dentro} dentro do canvas`);
console.log(`canvas:     ${canvas ? `${canvas.largura}x${canvas.altura}` : "AUSENTE"}`);
console.log(`pintura:    PNG do mapa com ${kbMapa.toFixed(1)} KB`);
console.log(`captura:    ${SAIDA}`);

// A contagem vem do mundo real, então o que se exige é ">0 e todos no lugar".
if (marcadores === 0) problemas.push("nenhum marcador renderizado");
if (marcadores && dentro !== marcadores)
  problemas.push(`marcadores visíveis: ${dentro} de ${marcadores} — fora do canvas`);

if (problemas.length) {
  console.log(`\nFALHOU (${problemas.length}):`);
  for (const p of problemas) console.log(`  · ${p}`);
  process.exit(1);
}
console.log("\nOK — mapa renderizou");
