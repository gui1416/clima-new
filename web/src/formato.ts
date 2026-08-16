/** Formatação pt-BR num lugar só: vírgula decimal, 24 h, fuso local. */

const NUM = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const DATA_HORA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function numero(v: number | null | undefined, decimais = 2): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: decimais,
    maximumFractionDigits: decimais,
  }).format(v);
}

export const inteiro = (v: number | null | undefined): string =>
  v === null || v === undefined ? "—" : NUM.format(v);

/** "há 8 min" para o recente, data curta para o resto. Tempo relativo só ajuda perto. */
export function instante(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  if (min < 60 * 24) return `há ${Math.round(min / 60)} h · ${HORA.format(d)}`;
  return DATA_HORA.format(d);
}

export const relogio = (d: Date | null): string => (d ? HORA.format(d) : "—");
