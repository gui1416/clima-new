/** Estilo do MapLibre, montado em código e sem nenhuma fonte externa.
 *
 * Não há servidor de tiles, nem de glifos, nem chave de API. A geometria é a
 * Natural Earth 1:50m que já estava no protótipo, convertida para lat/lon por
 * `scripts/geometria-do-prototipo.mjs`. O mapa é a tela principal do produto:
 * depender de tile de terceiro nele significaria limite de requisição e uma
 * conta a pagar por algo que já temos.
 *
 * Sem camada de `symbol`, portanto sem `glyphs` — rótulo de país entra depois,
 * com fonte própria, se entrar.
 *
 * As cores saem das custom properties de tokens.css, para que tema claro e
 * escuro não vivam em dois lugares.
 */

import type { FilterSpecification, StyleSpecification } from "maplibre-gl";

export type ColecaoPaises = GeoJSON.FeatureCollection<
  GeoJSON.MultiPolygon,
  { iso: string; nome: string }
>;

export const FONTE_PAISES = "paises";

/**
 * Cor em componentes sRGB inteiros. Toda cor entregue ao MapLibre passa por aqui.
 *
 * **O MapLibre não usa o parser de cor do navegador.** Ele tem o próprio, que
 * aceita hex, `rgb()`, `hsl()` e nomes — e rejeita o resto, invalidando o estilo
 * inteiro. Duas coisas já quebraram o mapa por isso:
 *
 * 1. `color-mix(...)` passado direto num `paint`.
 * 2. A tentativa óbvia de correção — resolver via `getComputedStyle` — porque o
 *    Chromium moderno serializa o valor computado de um `color-mix()` como
 *    `color(srgb 0.228 0.248 0.278)`, que o MapLibre também não parseia.
 *
 * A lição é não depender de *como* o navegador serializa cor. Aqui o navegador é
 * usado só para o que ele faz sem ambiguidade — normalizar qualquer sintaxe CSS
 * para hex, via `fillStyle` de canvas — e a aritmética de mistura é feita em
 * JavaScript. O que chega ao MapLibre é sempre `rgb(n, n, n)` montado a partir de
 * inteiros.
 */
type Rgb = readonly [number, number, number];

let ctx2d: CanvasRenderingContext2D | null = null;

function canvas(): CanvasRenderingContext2D {
  if (!ctx2d) {
    const c = document.createElement("canvas").getContext("2d");
    if (!c) throw new Error("canvas 2D indisponível — não é possível normalizar cores");
    ctx2d = c;
  }
  return ctx2d;
}

function paraRgb(valor: string): Rgb {
  // O CSSOM descarta valor inválido, deixando a propriedade vazia. É a checagem
  // mais barata que existe, e roda antes de qualquer coisa tocar o mapa.
  const sonda = document.createElement("span");
  sonda.style.color = valor;
  if (!sonda.style.color) throw new Error(`cor CSS inválida: ${valor}`);

  // `fillStyle` sempre devolve '#rrggbb' (ou 'rgba(...)' se houver alfa),
  // independente da sintaxe de entrada.
  const c = canvas();
  c.fillStyle = "#000000";
  c.fillStyle = valor;
  const normalizado = c.fillStyle;

  if (typeof normalizado === "string" && normalizado.startsWith("#")) {
    const n = parseInt(normalizado.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const nums = String(normalizado).match(/[\d.]+/g);
  if (!nums || nums.length < 3) throw new Error(`não foi possível normalizar a cor: ${valor}`);
  return [Number(nums[0]), Number(nums[1]), Number(nums[2])];
}

const paraCss = ([r, g, b]: Rgb): string => `rgb(${r}, ${g}, ${b})`;

function token(nome: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  if (!v) throw new Error(`token CSS ausente: ${nome}`);
  return paraCss(paraRgb(v));
}

/** Interpola em sRGB. Aritmética em JS, de propósito — ver :type:`Rgb`. */
function misturar(base: string, sobre: string, pctSobre: number): string {
  const a = paraRgb(base);
  const b = paraRgb(sobre);
  const t = pctSobre / 100;
  return paraCss([0, 1, 2].map((i) => Math.round(a[i]! + (b[i]! - a[i]!) * t)) as unknown as Rgb);
}

/**
 * @param isosComEvento ISO numéricos que têm evento visível — recebem terra mais
 *   clara, como no protótipo. Passar vazio deixa o mapa uniforme.
 */
export function estiloDoMapa(paises: ColecaoPaises, isosComEvento: string[]): StyleSpecification {
  const oceano = token("--ocean");
  const terra = token("--land");
  const contorno = token("--land-stroke");
  const terraComEvento = misturar(terra, token("--text"), 14);

  // `match` só aceita lista não vazia; sem eventos, usa a cor lisa.
  const corDaTerra = isosComEvento.length
    ? (["match", ["get", "iso"], isosComEvento, terraComEvento, terra] as const)
    : terra;

  return {
    version: 8,
    sources: {
      [FONTE_PAISES]: { type: "geojson", data: paises, promoteId: "iso" },
    },
    layers: [
      { id: "oceano", type: "background", paint: { "background-color": oceano } },
      {
        id: "terra",
        type: "fill",
        source: FONTE_PAISES,
        paint: { "fill-color": corDaTerra as never },
      },
      {
        id: "terra-contorno",
        type: "line",
        source: FONTE_PAISES,
        paint: { "line-color": contorno, "line-width": 0.6 },
      },
      {
        id: "terra-selecionada",
        type: "line",
        source: FONTE_PAISES,
        filter: ["==", ["get", "iso"], ""] as FilterSpecification,
        paint: { "line-color": token("--text"), "line-width": 1.4 },
      },
    ],
  };
}
