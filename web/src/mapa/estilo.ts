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

function token(nome: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  if (!v) throw new Error(`token CSS ausente: ${nome}`);
  return v;
}

/**
 * @param isosComEvento ISO numéricos que têm evento visível — recebem terra mais
 *   clara, como no protótipo. Passar vazio deixa o mapa uniforme.
 */
export function estiloDoMapa(paises: ColecaoPaises, isosComEvento: string[]): StyleSpecification {
  const oceano = token("--ocean");
  const terra = token("--land");
  const contorno = token("--land-stroke");
  const terraComEvento = `color-mix(in srgb, ${terra}, ${token("--text")} 14%)`;

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
