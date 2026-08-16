/** Carga dos dados estáticos.
 *
 * Buscados em runtime, não importados pelo bundler: a geometria tem ~187 KB e
 * entraria no JS principal, e `resolveJsonModule` faria o TypeScript inferir um
 * tipo literal gigante a cada checagem.
 *
 * Além disso, buscar por rede é a forma que estes dois vão continuar funcionando
 * quando saírem de arquivo estático para endpoint: na Fase 3 a geometria vira
 * tile vetorial do PostGIS e os eventos vêm da API, e só as URLs mudam.
 */

import type { ArquivoEventosDemo, Evento } from "../tipos";

type ColecaoPaises = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon, { iso: string; nome: string }>;

let paisesEmCache: Promise<ColecaoPaises> | null = null;
let eventosEmCache: Promise<Evento[]> | null = null;

async function buscarJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`falha ao carregar ${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export function carregarPaises(): Promise<ColecaoPaises> {
  paisesEmCache ??= buscarJson<ColecaoPaises>("/dados/paises.json");
  return paisesEmCache;
}

/** Eventos de DEMONSTRAÇÃO, extraídos do protótipo. Substituídos pela API na Fase 3. */
export function carregarEventosDemo(): Promise<Evento[]> {
  eventosEmCache ??= buscarJson<ArquivoEventosDemo>("/dados/eventos-demo.json").then((a) => {
    if (!a.demo) throw new Error("arquivo de eventos sem marca de demonstração");
    return a.eventos;
  });
  return eventosEmCache;
}
