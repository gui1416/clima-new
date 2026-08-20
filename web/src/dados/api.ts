/** Cliente da API e o hook de atualização periódica.
 *
 * A cadência de 60 s não é arbitrária: é o intervalo de coleta do USGS, que
 * também é o `max-age` que o próprio feed declara. Buscar mais rápido não traz
 * dado novo — traz o mesmo dado com um timestamp diferente.
 *
 * Sem WebSocket ainda. Ele só ganha sentido quando houver fonte que mude mais
 * rápido que a janela de coleta; até lá, polling entrega a mesma frescura com
 * bem menos peça móvel.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import type {
  Estatisticas,
  EventoDetalhe,
  Pagina,
  Saude,
  SaudeFonte,
} from "../tipos";

export const CADENCIA_MS = 60_000;

async function buscar<T>(caminho: string): Promise<T> {
  const r = await fetch(caminho, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${caminho}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export interface FiltroEventos {
  horas?: number;
  magnitudeMinima?: number;
  severidade?: string;
  limite?: number;
  /** Só eventos com pelo menos N fontes confirmando. `2` isola o diferencial. */
  fontesMinimas?: number;
  /** "oeste,sul,leste,norte". Recorta pelo enquadramento visível do mapa. */
  bbox?: string;
  /** Cursor devolvido em `proximo_cursor` pela página anterior. */
  cursor?: string;
}

export function urlEventos(f: FiltroEventos = {}): string {
  const q = new URLSearchParams({
    horas: String(f.horas ?? 24),
    magnitude_minima: String(f.magnitudeMinima ?? 2.5),
    limite: String(f.limite ?? 500),
  });
  if (f.severidade) q.set("severidade", f.severidade);
  if (f.fontesMinimas) q.set("fontes_minimas", String(f.fontesMinimas));
  if (f.bbox) q.set("bbox", f.bbox);
  if (f.cursor) q.set("cursor", f.cursor);
  return `/api/eventos?${q}`;
}

export const listarEventos = (f: FiltroEventos = {}) => buscar<Pagina>(urlEventos(f));
export const detalharEvento = (id: string) =>
  buscar<EventoDetalhe>(`/api/eventos/${encodeURIComponent(id)}`);
export const buscarEstatisticas = (horas = 24, magnitudeMinima = 2.5) =>
  buscar<Estatisticas>(`/api/estatisticas?horas=${horas}&magnitude_minima=${magnitudeMinima}`);
export const buscarFontes = () => buscar<SaudeFonte[]>("/saude/fontes");

/** `/saude` responde 503 quando a coleta tem lacuna — o corpo continua sendo JSON
 *  útil, e é justamente o caso que interessa mostrar. Por isso não usa `buscar`. */
export async function buscarSaude(): Promise<Saude> {
  const r = await fetch("/saude", { headers: { accept: "application/json" } });
  if (r.status !== 200 && r.status !== 503) throw new Error(`/saude: HTTP ${r.status}`);
  return (await r.json()) as Saude;
}

export interface Periodico<T> {
  dado: T | null;
  erro: string | null;
  carregando: boolean;
  atualizadoEm: Date | null;
}

/**
 * Busca agora e a cada `cadencia`. Também revalida quando a aba volta ao foco —
 * um mapa deixado aberto por horas mostrando dado velho é pior que um vazio.
 */
export function usePeriodico<T>(
  buscarDado: () => Promise<T>,
  deps: unknown[] = [],
  cadencia = CADENCIA_MS,
): Periodico<T> {
  const [estado, setEstado] = useState<Periodico<T>>({
    dado: null,
    erro: null,
    carregando: true,
    atualizadoEm: null,
  });
  // Mantém a função fora das dependências do efeito: uma arrow nova a cada render
  // reiniciaria o intervalo sem parar.
  const fn = useRef(buscarDado);
  fn.current = buscarDado;

  useEffect(() => {
    let vivo = true;

    const ciclo = async () => {
      try {
        const dado = await fn.current();
        if (vivo) setEstado({ dado, erro: null, carregando: false, atualizadoEm: new Date() });
      } catch (e) {
        // Preserva o último dado bom: uma falha momentânea de rede não deve
        // esvaziar o mapa.
        if (vivo) {
          setEstado((a) => ({
            ...a,
            erro: e instanceof Error ? e.message : String(e),
            carregando: false,
          }));
        }
      }
    };

    void ciclo();
    const timer = window.setInterval(ciclo, cadencia);
    const aoFocar = () => {
      if (document.visibilityState === "visible") void ciclo();
    };
    document.addEventListener("visibilitychange", aoFocar);

    return () => {
      vivo = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", aoFocar);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cadencia, ...deps]);

  return estado;
}

// ── fluxo ao vivo ───────────────────────────────────────────────────────────

export type EstadoFluxo = "conectando" | "ao-vivo" | "offline";

export interface Fluxo {
  estado: EstadoFluxo;
  /** Incrementa a cada delta recebido. Serve de dependência para revalidar. */
  revisao: number;
}

/**
 * Assinatura única de `/api/eventos/stream`, compartilhada por toda a aplicação.
 *
 * **Por que um singleton de módulo e não estado por componente.** Quatro telas
 * consomem o fluxo, e a primeira versão abria um socket por chamada do hook —
 * quatro conexões para o mesmo dado. Pior: em `StrictMode` o React monta, executa
 * o efeito, desmonta e remonta no mesmo tick, e a limpeza fechava o socket no
 * meio do handshake ("closed before the connection is established"), o que
 * derrubava a conexão e ligava o backoff. O resultado era uma pílula presa em
 * "sem fluxo" com uma enxurrada de reconexões por trás.
 *
 * Com uma conexão só e contagem de assinantes, remontar é barato, e o desligamento
 * é adiado alguns segundos justamente para atravessar o remount sem derrubar nada.
 *
 * O socket **não** é a fonte dos dados da tela, de propósito. Ele emite todo
 * evento atualizado desde `desde`, sem os filtros da consulta atual (janela,
 * magnitude mínima, severidade, bbox) — costurar esses deltas na lista filtrada
 * exigiria reimplementar no navegador os predicados que já vivem no SQL, e as
 * duas cópias divergiriam. Aqui o delta só diz "mudou alguma coisa"; quem sabe o
 * que a tela deve mostrar continua sendo a consulta REST com seus filtros.
 *
 * O custo é um round-trip a mais por delta. O ganho é ter uma única definição de
 * "o que está visível" — e um indicador "ao vivo" que só acende quando de fato está.
 */

const ESPERA_ENCERRAMENTO_MS = 4000;
const BACKOFF_MAXIMO_MS = 30_000;

// `useSyncExternalStore` compara instantâneos por identidade: o objeto só pode
// ser recriado quando algo de fato mudou, ou o React entra em laço de render.
let instantaneo: Fluxo = { estado: "conectando", revisao: 0 };
let socket: WebSocket | null = null;
let desde: string | null = null;
let tentativa = 0;
let religar: number | undefined;
let encerrar: number | undefined;
const inscritos = new Set<() => void>();

function publicar(proximo: Partial<Fluxo>): void {
  const combinado = { ...instantaneo, ...proximo };
  if (combinado.estado === instantaneo.estado && combinado.revisao === instantaneo.revisao) return;
  instantaneo = combinado;
  for (const cb of inscritos) cb();
}

function conectar(): void {
  if (socket || !inscritos.size) return;
  const protocolo = location.protocol === "https:" ? "wss:" : "ws:";
  // Continua de onde parou depois de uma queda: sem isto, a reconexão
  // reprocessaria o backlog inteiro a cada corte de rede.
  const q = desde ? `?desde=${encodeURIComponent(desde)}` : "";

  let s: WebSocket;
  try {
    s = new WebSocket(`${protocolo}//${location.host}/api/eventos/stream${q}`);
  } catch {
    publicar({ estado: "offline" });
    return;
  }
  socket = s;

  s.onopen = () => {
    tentativa = 0;
    publicar({ estado: "ao-vivo" });
  };

  s.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data as string) as { tipo?: string; desde?: string };
      if (typeof msg.desde === "string") desde = msg.desde;
      if (msg.tipo === "delta") publicar({ estado: "ao-vivo", revisao: instantaneo.revisao + 1 });
      else publicar({ estado: "ao-vivo" });
    } catch {
      // Quadro malformado não derruba a assinatura: o polling continua de pé.
    }
  };

  s.onerror = () => s.close();

  s.onclose = () => {
    socket = null;
    if (!inscritos.size) return;
    publicar({ estado: "offline" });
    // Backoff até 30 s. Servidor reiniciando não deve levar uma enxurrada.
    const espera = Math.min(BACKOFF_MAXIMO_MS, 1000 * 2 ** tentativa++);
    window.clearTimeout(religar);
    religar = window.setTimeout(conectar, espera);
  };
}

function desligar(): void {
  window.clearTimeout(religar);
  if (!socket) return;
  // `onclose` desarmado primeiro: senão o fechamento voluntário agenda uma
  // reconexão para um fluxo que ninguém está mais ouvindo.
  socket.onclose = null;
  socket.close();
  socket = null;
  instantaneo = { estado: "conectando", revisao: instantaneo.revisao };
}

function assinar(aoMudar: () => void): () => void {
  inscritos.add(aoMudar);
  window.clearTimeout(encerrar);
  conectar();
  return () => {
    inscritos.delete(aoMudar);
    if (inscritos.size) return;
    // Adiado de propósito: o remount do StrictMode e a troca de rota
    // desinscrevem e reinscrevem no mesmo tick, e fechar na hora custaria um
    // handshake inteiro a cada navegação.
    encerrar = window.setTimeout(desligar, ESPERA_ENCERRAMENTO_MS);
  };
}

const ler = (): Fluxo => instantaneo;
// Sem `window` não há socket: no servidor o fluxo é sempre "offline", e as telas
// caem no polling sem nenhum ramo especial.
const lerNoServidor = (): Fluxo => ({ estado: "offline", revisao: 0 });

export function useFluxoDeEventos(): Fluxo {
  return useSyncExternalStore(assinar, ler, lerNoServidor);
}
