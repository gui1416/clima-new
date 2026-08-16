/**
 * Converte a geometria Natural Earth embutida no protótipo em GeoJSON lat/lon.
 *
 * O protótipo guarda os países como paths SVG já *projetados* — a projeção
 * equirretangular foi aplicada na geração. Mas a transformação é linear e
 * conhecida, portanto invertível:
 *
 *     projX(lon) = (lon + 180) * K        K = WORLD.w / 360
 *     projY(lat) = (latTop - lat) * K
 *
 * Então o mesmo dado 1:50m que já está no repositório serve ao MapLibre sem
 * baixar nada. O front fica sem dependência de tiles de terceiro, o que é o
 * mesmo princípio de autocontenção do protótipo — e evita chave de API e limite
 * de requisição num mapa que é a tela principal do produto.
 *
 * Uso: npm run dados
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
const PROTOTIPO = resolve(AQUI, "../../clima-global-prototipo-v2.html");
const SAIDA = resolve(AQUI, "../public/dados/paises.json");

// Precisão da fonte é ~0,1 unidade projetada ≈ 0,036° ≈ 4 km. Três decimais de
// grau (~110 m) já é mais do que o dado carrega; mais que isso só engorda o arquivo.
const DECIMAIS = 3;

function extrairWorld(html) {
  const inicio = html.indexOf("const WORLD = ");
  if (inicio === -1) throw new Error("WORLD não encontrado no protótipo");
  const abre = html.indexOf("{", inicio);
  // O blob é uma linha só terminada em `};`
  const fecha = html.indexOf("};", abre);
  if (fecha === -1) throw new Error("fim do blob WORLD não encontrado");
  return JSON.parse(html.slice(abre, fecha + 1));
}

/** "M x y x y ... Z M x y ... Z" → [[[x,y], ...], ...] (um anel por subpath) */
function aneisDoPath(d) {
  return d
    .split("M")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((sub) => {
      const nums = sub.match(/-?\d*\.?\d+/g);
      if (!nums) return null;
      const pontos = [];
      for (let i = 0; i + 1 < nums.length; i += 2) {
        pontos.push([Number(nums[i]), Number(nums[i + 1])]);
      }
      return pontos;
    })
    .filter((p) => p && p.length >= 3);
}

const html = readFileSync(PROTOTIPO, "utf8");
const WORLD = extrairWorld(html);
const K = WORLD.w / 360;

const arred = (n) => Number(n.toFixed(DECIMAIS));
const lonDe = (x) => arred(x / K - 180);
const latDe = (y) => arred(WORLD.latTop - y / K);

/**
 * O gerador do protótipo emite duas cópias do que cruza o antimeridiano — o mesmo
 * anel deslocado 360°, para aparecer nas duas bordas de um mapa plano. A Rússia é
 * o caso grande (677 pontos duplicados, uma cópia em lon 27→190 e outra em
 * -333→-170); a ilha de Wrangel é o caso pequeno.
 *
 * O MapLibre não precisa dessa duplicata: ele já repete o mundo ao rolar. Manter
 * as duas cópias desenharia a Rússia atravessada no oceano Atlântico.
 *
 * Regra: agrupa anéis por assinatura (nº de pontos + faixa de latitude, que a
 * translação em longitude não altera) e mantém, de cada grupo, o que tem maior
 * sobreposição com [-180, 180].
 */
function removerCopiasDeslocadas(aneis) {
  const sobreposicao = (r) => {
    const lons = r.map(([lo]) => lo);
    const a = Math.max(Math.min(...lons), -180);
    const b = Math.min(Math.max(...lons), 180);
    return Math.max(0, b - a);
  };
  const assinatura = (r) => {
    const lats = r.map(([, la]) => la);
    return `${r.length}:${Math.min(...lats).toFixed(2)}:${Math.max(...lats).toFixed(2)}`;
  };

  const melhores = new Map();
  for (const r of aneis) {
    const chave = assinatura(r);
    const atual = melhores.get(chave);
    if (!atual || sobreposicao(r) > sobreposicao(atual)) melhores.set(chave, r);
  }
  return [...melhores.values()];
}

let descartados = 0;
let copiasRemovidas = 0;
const features = [];

for (const pais of WORLD.countries) {
  const poligonos = [];

  const brutos = aneisDoPath(pais.d).map((anel) =>
    anel.map(([x, y]) => [lonDe(x), latDe(y)]),
  );
  const aneis = removerCopiasDeslocadas(brutos);
  copiasRemovidas += brutos.length - aneis.length;

  for (const ring of aneis) {
    // GeoJSON exige anel fechado; o Z do SVG fecha implicitamente.
    const [p0] = ring;
    const pn = ring[ring.length - 1];
    if (p0[0] !== pn[0] || p0[1] !== pn[1]) ring.push([p0[0], p0[1]]);
    if (ring.length < 4) {
      descartados++;
      continue;
    }
    poligonos.push([ring]);
  }

  if (!poligonos.length) {
    descartados++;
    continue;
  }

  features.push({
    type: "Feature",
    // ISO 3166-1 numérico como string — a mesma chave que liga evento a país.
    id: pais.i,
    properties: { iso: pais.i, nome: pais.n },
    geometry: { type: "MultiPolygon", coordinates: poligonos },
  });
}

const colecao = { type: "FeatureCollection", features };

mkdirSync(dirname(SAIDA), { recursive: true });
writeFileSync(SAIDA, JSON.stringify(colecao));

const kb = (Buffer.byteLength(JSON.stringify(colecao)) / 1024).toFixed(0);
console.log(`${features.length} países → ${SAIDA}`);
console.log(
  `${kb} KB, ${DECIMAIS} decimais, ${copiasRemovidas} cópias deslocadas removidas, ` +
    `${descartados} anéis degenerados descartados`,
);
console.log(
  `recorte de latitude do protótipo: ${WORLD.latBottom}° a ${WORLD.latTop}° ` +
    `(Antártida fora do dado)`,
);
