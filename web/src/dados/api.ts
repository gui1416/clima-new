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

import { useEffect, useRef, useState } from "react";

import type {
  Estatisticas,
  EventoDetalhe,
  Pagina,
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
}

export function urlEventos(f: FiltroEventos = {}): string {
  const q = new URLSearchParams({
    horas: String(f.horas ?? 24),
    magnitude_minima: String(f.magnitudeMinima ?? 2.5),
    limite: String(f.limite ?? 500),
  });
  if (f.severidade) q.set("severidade", f.severidade);
  return `/api/eventos?${q}`;
}

export const listarEventos = (f: FiltroEventos = {}) => buscar<Pagina>(urlEventos(f));
export const detalharEvento = (id: string) =>
  buscar<EventoDetalhe>(`/api/eventos/${encodeURIComponent(id)}`);
export const buscarEstatisticas = (horas = 24, magnitudeMinima = 2.5) =>
  buscar<Estatisticas>(`/api/estatisticas?horas=${horas}&magnitude_minima=${magnitudeMinima}`);
export const buscarFontes = () => buscar<SaudeFonte[]>("/saude/fontes");

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
