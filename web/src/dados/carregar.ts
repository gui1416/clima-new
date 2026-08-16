/** Carga da geometria dos países.
 *
 * Buscada em runtime, não importada pelo bundler: tem ~187 KB e entraria no JS
 * principal, e `resolveJsonModule` faria o TypeScript inferir um tipo literal
 * gigante a cada checagem.
 *
 * Os eventos **não** vêm daqui — vêm da API (`dados/api.ts`). Os 18 eventos de
 * demonstração do protótipo foram removidos quando o back-end passou a entregar
 * sismos reais do USGS.
 */

type ColecaoPaises = GeoJSON.FeatureCollection<GeoJSON.MultiPolygon, { iso: string; nome: string }>;

let paisesEmCache: Promise<ColecaoPaises> | null = null;

export function carregarPaises(): Promise<ColecaoPaises> {
  paisesEmCache ??= (async () => {
    const r = await fetch("/dados/paises.json");
    if (!r.ok) throw new Error(`falha ao carregar geometria: HTTP ${r.status}`);
    return (await r.json()) as ColecaoPaises;
  })();
  return paisesEmCache;
}
