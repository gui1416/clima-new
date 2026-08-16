/**
 * Extrai os 18 eventos de demonstração do protótipo para JSON.
 *
 * Transcrever à mão convidaria a erro e criaria uma segunda fonte de verdade. O
 * protótipo continua sendo a especificação; isto só o lê.
 *
 * Estes dados são de DEMONSTRAÇÃO e existem apenas até a API de produto (Fase 3).
 * O campo `demo: true` no arquivo gerado é para que nada na interface os
 * apresente como reais por acidente.
 *
 * Uso: npm run dados
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = dirname(fileURLToPath(import.meta.url));
const PROTOTIPO = resolve(AQUI, "../../clima-global-prototipo-v2.html");
const SAIDA = resolve(AQUI, "../public/dados/eventos-demo.json");

const html = readFileSync(PROTOTIPO, "utf8");

const inicio = html.indexOf("const EVENTS = [");
if (inicio === -1) throw new Error("EVENTS não encontrado no protótipo");
const abre = html.indexOf("[", inicio);
const fecha = html.indexOf("\n    ];", abre);
if (fecha === -1) throw new Error("fim do array EVENTS não encontrado");

const literal = html.slice(abre, fecha + 6);

// É um literal de array com chaves sem aspas — não é JSON. Avaliar é seguro aqui:
// a entrada é um arquivo do próprio repositório, contendo só dados.
const eventos = new Function(`return ${literal}`)();

if (!Array.isArray(eventos) || eventos.length === 0) {
  throw new Error("EVENTS não avaliou para um array não vazio");
}

const obrigatorios = ["id", "title", "lat", "lon", "severity", "type", "countryId"];
for (const e of eventos) {
  for (const campo of obrigatorios) {
    if (e[campo] === undefined) throw new Error(`evento ${e.id} sem campo ${campo}`);
  }
  if (e.lat < -90 || e.lat > 90 || e.lon < -180 || e.lon > 180) {
    throw new Error(`evento ${e.id} com coordenada inválida: ${e.lat},${e.lon}`);
  }
}

const saida = {
  demo: true,
  origem: "clima-global-prototipo-v2.html",
  geradoEm: new Date().toISOString(),
  eventos,
};

mkdirSync(dirname(SAIDA), { recursive: true });
writeFileSync(SAIDA, JSON.stringify(saida, null, 2));

console.log(`${eventos.length} eventos de demonstração → ${SAIDA}`);
console.log(`tipos: ${[...new Set(eventos.map((e) => e.type))].join(", ")}`);
