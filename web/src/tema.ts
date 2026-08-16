/** Tema claro/escuro.
 *
 * Mesmo contrato do protótipo — atributo `data-theme` no `<html>`, escuro por
 * padrão, persistido em `localStorage['clima-theme']` — para que os dois possam
 * conviver sem divergir.
 *
 * Existe um barramento de inscrição porque o MapLibre não lê CSS: o estilo do
 * mapa é montado a partir dos tokens em JavaScript e precisa ser reconstruído
 * quando o tema muda.
 */

export type Tema = "dark" | "light";

const CHAVE = "clima-theme";
const ouvintes = new Set<() => void>();

function ehTema(v: string | null): v is Tema {
  return v === "dark" || v === "light";
}

export function temaAtual(): Tema {
  // O `?? null` precisa ficar na variável, não na chamada: o type guard estreita
  // o identificador que recebe, não uma expressão calculada no argumento.
  const attr = document.documentElement.dataset.theme ?? null;
  return ehTema(attr) ? attr : "dark";
}

export function aplicarTema(t: Tema): void {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(CHAVE, t);
  } catch {
    // Navegação privada ou storage bloqueado: o tema vale só para a sessão.
  }
  for (const cb of ouvintes) cb();
}

export function alternarTema(): Tema {
  const proximo: Tema = temaAtual() === "dark" ? "light" : "dark";
  aplicarTema(proximo);
  return proximo;
}

/** Restaura a preferência salva. Chamar uma vez, antes de renderizar. */
export function iniciarTema(): void {
  let salvo: string | null = null;
  try {
    salvo = localStorage.getItem(CHAVE);
  } catch {
    salvo = null;
  }
  document.documentElement.dataset.theme = ehTema(salvo) ? salvo : "dark";
}

/** Inscreve um ouvinte e devolve a função de cancelamento. */
export function aoTrocarTema(cb: () => void): () => void {
  ouvintes.add(cb);
  return () => ouvintes.delete(cb);
}
