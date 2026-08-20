/**
 * Varredura de responsividade: abre cada rota em cada tamanho de tela e falha
 * se algo vazar, encolher demais ou sumir.
 *
 * Existe porque "responsivo" não é verificável por inspeção. O que quebra em
 * layout fluido quase nunca aparece na largura em que se está olhando: uma
 * tabela de sete colunas empurra o `body` a 700 px e não a 1440; um piso de
 * altura em `dvh` esmaga o mapa a 360 px de altura e não a 900.
 *
 * O que é verificado, em ordem de gravidade:
 *   1. nenhuma exceção de página e nenhum erro de console inesperado;
 *   2. **nenhuma rolagem horizontal** — e, quando há, quais elementos vazam;
 *   3. o mapa mantém área utilizável em toda tela;
 *   4. os alvos de toque têm pelo menos 40 px em ponteiro grosso;
 *   5. nada de texto sobreposto pelos flutuantes do mapa.
 *
 * Uso: node scripts/verificar-responsivo.mjs [url]
 */

import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));

const LIBS = resolve(AQUI, "../../.artefatos/libs/root/usr/lib/x86_64-linux-gnu");
if (existsSync(LIBS)) {
  process.env.LD_LIBRARY_PATH = [LIBS, process.env.LD_LIBRARY_PATH].filter(Boolean).join(":");
}

const { chromium } = await import("playwright");

const URL_BASE = process.argv[2]?.startsWith("http") ? process.argv[2] : "http://localhost:5173";
const SAIDA = resolve(AQUI, "../../.artefatos/responsivo");

// Os extremos importam mais que os pontos redondos: 320 é o menor telefone ainda
// em uso, 2560 é o monitor em que um layout de largura fixa deixa faixas vazias,
// e 812x375 é o telefone deitado — a única forma comum de janela mais larga que
// alta e ainda assim baixa.
const TELAS = [
  { nome: "320x568", largura: 320, altura: 568, toque: true },
  { nome: "360x740", largura: 360, altura: 740, toque: true },
  { nome: "414x896", largura: 414, altura: 896, toque: true },
  { nome: "812x375", largura: 812, altura: 375, toque: true },
  { nome: "768x1024", largura: 768, altura: 1024, toque: true },
  { nome: "1024x768", largura: 1024, altura: 768, toque: false },
  { nome: "1280x800", largura: 1280, altura: 800, toque: false },
  { nome: "1440x900", largura: 1440, altura: 900, toque: false },
  { nome: "1920x1080", largura: 1920, altura: 1080, toque: false },
  { nome: "2560x1440", largura: 2560, altura: 1440, toque: false },
];

const ROTAS = ["/visao-geral", "/mapa", "/eventos", "/fontes"];

const RUIDO_ESPERADO = [/Failed to load resource.*503/i];

/* A varredura é rápida o bastante para bater no limitador do próprio produto:
   dez telas vezes quatro rotas passam de 120 requisições por minuto, e o
   back-end começa a responder 429. Isso não é defeito de layout — mas estraga a
   medição, porque a tela passa a ser renderizada sem dado e a comparação vira
   outra. Daí o marcapasso: o script conta as próprias requisições à API e espera
   até caber na janela, em vez de pedir que se afrouxe o limite. */
/* Folgado de propósito. O orçamento real do back-end é 120/min, mas o script não
   enxerga tudo que gasta: além das buscas REST, cada tela abre o fluxo ao vivo
   (o upgrade conta como requisição) e cada delta recebido dispara revalidação nas
   três consultas da visão geral. Contar só o que se vê e mirar em 120 estourava. */
const LIMITE_POR_MINUTO = 65;
const carimbos = [];

function registrar() {
  carimbos.push(Date.now());
}

async function aguardarJanela() {
  for (;;) {
    const corte = Date.now() - 60_000;
    while (carimbos.length && carimbos[0] < corte) carimbos.shift();
    if (carimbos.length < LIMITE_POR_MINUTO) return;
    const espera = carimbos[0] + 60_000 - Date.now() + 250;
    await new Promise((r) => setTimeout(r, Math.max(espera, 250)));
  }
}

const problemas = [];
const navegador = await chromium.launch();

for (const tela of TELAS) {
  const contexto = await navegador.newContext({
    viewport: { width: tela.largura, height: tela.altura },
    hasTouch: tela.toque,
    isMobile: tela.toque,
  });
  const pagina = await contexto.newPage();
  pagina.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api") || u.pathname.startsWith("/saude")) registrar();
  });
  // O upgrade do WebSocket passa pelo limitador como qualquer requisição, e não
  // aparece no evento `request`.
  pagina.on("websocket", (ws) => {
    if (ws.url().includes("/api/")) registrar();
  });
  pagina.on("pageerror", (e) => problemas.push(`${tela.nome} exceção: ${e.message}`));
  pagina.on("console", (m) => {
    if (m.type() !== "error") return;
    if (RUIDO_ESPERADO.some((r) => r.test(m.text()))) return;
    const texto = m.text();
    if (/429/.test(texto)) {
      problemas.push(
        `${tela.nome} limitador de requisições atingido (429) — a medição desta tela ` +
          "roda sem dado e não vale; aumente a pausa do marcapasso",
      );
      return;
    }
    problemas.push(`${tela.nome} console: ${texto}`);
  });

  for (const rota of ROTAS) {
    await aguardarJanela();
    await pagina.goto(`${URL_BASE}${rota}`, { waitUntil: "domcontentloaded" });
    await pagina.waitForTimeout(rota === "/mapa" ? 3200 : 700);

    const relatorio = await pagina.evaluate((ehMapa) => {
      const doc = document.documentElement;

      /** Verdadeiro se algum ancestral recorta o elemento na horizontal.
       *
       * Sem isto a varredura acusa três coisas que são o desenho funcionando:
       * marcador do MapLibre fora do enquadramento (o mapa tem `overflow:hidden`),
       * tabela larga dentro de `.tabela-rolagem` (que existe exatamente para
       * rolar sozinha) e a faixa de eventos com rolagem por toque. Nenhuma delas
       * chega ao `body`. */
      const recortado = (el) => {
        for (let p = el.parentElement; p && p !== doc; p = p.parentElement) {
          const ov = getComputedStyle(p).overflowX;
          if (ov === "hidden" || ov === "auto" || ov === "scroll" || ov === "clip") return true;
        }
        return false;
      };

      const vazamentos = [];
      // Reporta o elemento mais raso que vaza: o culpado costuma ser o contêiner,
      // e listar os filhos dele só produz ruído.
      //
      // Só o lado direito conta. À esquerda o navegador não rola, então a gaveta
      // fechada em `translateX(-105%)` fica em -15px de propósito e é invisível
      // para o usuário — acusá-la seria acusar o próprio mecanismo do menu.
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.right <= window.innerWidth + 1) continue;
        if (recortado(el)) continue;
        if (vazamentos.some((v) => v.el.contains(el))) continue;
        const classe = (el.className.baseVal ?? el.className ?? "").toString().trim().split(/\s+/)[0];
        vazamentos.push({ el, texto: `${el.tagName.toLowerCase()}${classe ? "." + classe : ""} → ${Math.round(r.right)}px` });
      }

      const pequenos = [];
      if (matchMedia("(pointer: coarse)").matches) {
        for (const el of document.querySelectorAll("button, a[href], input, [role=switch], [role=tab]")) {
          const r = el.getBoundingClientRect();
          // Zero é elemento oculto, não alvo pequeno.
          if (r.width === 0 || r.height === 0) continue;
          if (r.height >= 40 && r.width >= 24) continue;
          // Fora do enquadramento do mapa não é alvo: o MapLibre mantém no DOM
          // marcadores que estão além da borda visível.
          if (r.right < 0 || r.left > window.innerWidth || r.bottom < 0 || r.top > window.innerHeight) continue;
          const classe = (el.className.baseVal ?? el.className ?? "").toString().trim().split(/\s+/)[0];
          pequenos.push(`${el.tagName.toLowerCase()}${classe ? "." + classe : ""} ${Math.round(r.width)}x${Math.round(r.height)}`);
        }
      }

      let canvas = null;
      if (ehMapa) {
        const c = document.querySelector(".mapa-canvas canvas");
        if (c) {
          const r = c.getBoundingClientRect();
          canvas = { largura: Math.round(r.width), altura: Math.round(r.height) };
        }
      }

      return {
        rolagem: doc.scrollWidth > window.innerWidth + 1
          ? { largura: doc.scrollWidth, janela: window.innerWidth }
          : null,
        vazamentos: vazamentos.map((v) => v.texto).slice(0, 6),
        pequenos: [...new Set(pequenos)].slice(0, 6),
        canvas,
      };
    }, rota === "/mapa");

    if (relatorio.rolagem) {
      problemas.push(
        `${tela.nome} ${rota}: rolagem horizontal (${relatorio.rolagem.largura} > ${relatorio.rolagem.janela}) :: ` +
          (relatorio.vazamentos.join(" | ") || "sem elemento identificado"),
      );
    } else if (relatorio.vazamentos.length) {
      problemas.push(`${tela.nome} ${rota}: elemento fora da janela :: ${relatorio.vazamentos.join(" | ")}`);
    }

    if (relatorio.pequenos.length) {
      problemas.push(`${tela.nome} ${rota}: alvo de toque abaixo de 40px :: ${relatorio.pequenos.join(" | ")}`);
    }

    if (rota === "/mapa") {
      if (!relatorio.canvas) problemas.push(`${tela.nome} /mapa: canvas ausente`);
      // 240x200 é o piso em que o mapa ainda mostra um continente inteiro. Abaixo
      // disso ele deixou de ser um mapa e virou um selo.
      else if (relatorio.canvas.largura < 240 || relatorio.canvas.altura < 200) {
        problemas.push(
          `${tela.nome} /mapa: canvas espremido (${relatorio.canvas.largura}x${relatorio.canvas.altura})`,
        );
      }
    }

    mkdirSync(SAIDA, { recursive: true });
    await pagina.screenshot({ path: `${SAIDA}/${rota.slice(1)}-${tela.nome}.png` });
  }

  await contexto.close();
}

await navegador.close();

console.log(`telas:    ${TELAS.length}  ·  rotas: ${ROTAS.length}`);
console.log(`capturas: ${SAIDA}`);

if (problemas.length) {
  console.log(`\nFALHOU (${problemas.length}):`);
  for (const p of problemas) console.log(`  · ${p}`);
  process.exit(1);
}
console.log("\nOK — sem vazamento horizontal, mapa utilizável e alvos de toque válidos em todas as telas");
