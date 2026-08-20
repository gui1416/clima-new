/** Busca global (Cmd/Ctrl+K), portada do protótipo (`:511`) sobre dado real.
 *
 * No protótipo ela filtrava os 18 eventos de demonstração em memória. Aqui a
 * consulta vai ao back-end com janela larga (72 h) e piso de magnitude zero:
 * quem digita o nome de um lugar quer achar o evento, não descobrir que ele
 * estava abaixo do corte de apresentação da tela anterior.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { listarEventos } from "../dados/api";
import { instante, numero } from "../formato";
import { ROTULO_SEVERIDADE, type EventoResumo } from "../tipos";
import { Icone, type NomeIcone } from "./Icones";

export interface AlvoNavegacao {
  caminho: string;
  rotulo: string;
  icone: NomeIcone;
}

const normalizar = (s: string) =>
  s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

export function PaletaComandos({
  aberta,
  aoFechar,
  rotas,
}: {
  aberta: boolean;
  aoFechar: () => void;
  rotas: readonly AlvoNavegacao[];
}) {
  const [termo, setTermo] = useState("");
  const [eventos, setEventos] = useState<EventoResumo[]>([]);
  const [foco, setFoco] = useState(0);
  const entrada = useRef<HTMLInputElement>(null);
  const navegar = useNavigate();

  // Carrega uma vez por abertura. Buscar a cada tecla castigaria o back-end para
  // filtrar sobre um conjunto que cabe na memória do navegador.
  useEffect(() => {
    if (!aberta) return;
    setTermo("");
    setFoco(0);
    let vivo = true;
    listarEventos({ horas: 72, magnitudeMinima: 0, limite: 300 })
      .then((p) => vivo && setEventos(p.itens))
      .catch(() => vivo && setEventos([]));
    const t = window.setTimeout(() => entrada.current?.focus(), 40);
    return () => {
      vivo = false;
      window.clearTimeout(t);
    };
  }, [aberta]);

  const q = normalizar(termo.trim());
  const rotasFiltradas = useMemo(
    () => rotas.filter((r) => !q || normalizar(r.rotulo).includes(q)),
    [rotas, q],
  );
  const eventosFiltrados = useMemo(
    () =>
      (q
        ? eventos.filter((e) => normalizar(`${e.titulo} ${e.lugar ?? ""}`).includes(q))
        : eventos
      ).slice(0, 6),
    [eventos, q],
  );

  const itens = useMemo(
    () => [
      ...rotasFiltradas.map((r) => ({ tipo: "rota" as const, chave: r.caminho, rota: r })),
      ...eventosFiltrados.map((e) => ({ tipo: "evento" as const, chave: e.id, evento: e })),
    ],
    [rotasFiltradas, eventosFiltrados],
  );

  useEffect(() => setFoco(0), [termo]);

  if (!aberta) return null;

  const acionar = (i: number) => {
    const alvo = itens[i];
    if (!alvo) return;
    aoFechar();
    if (alvo.tipo === "rota") navegar(alvo.rota.caminho);
    // O mapa lê `?evento=` e seleciona/aproxima. Ver `MapaGlobal`.
    else navegar(`/mapa?evento=${encodeURIComponent(alvo.evento.id)}`);
  };

  const aoTeclar = (ev: React.KeyboardEvent) => {
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setFoco((f) => (itens.length ? (f + 1) % itens.length : 0));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setFoco((f) => (itens.length ? (f - 1 + itens.length) % itens.length : 0));
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      acionar(foco);
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      aoFechar();
    }
  };

  return (
    <>
      <button type="button" className="scrim-paleta" onClick={aoFechar} aria-label="Fechar busca" />
      <div className="paleta" role="dialog" aria-modal="true" aria-label="Busca global">
        <label className="paleta-busca">
          <Icone nome="search" />
          <input
            ref={entrada}
            value={termo}
            onChange={(e) => setTermo(e.target.value)}
            onKeyDown={aoTeclar}
            placeholder="Buscar evento, lugar ou navegar para…"
            aria-label="Buscar evento, lugar ou módulo"
            // Combobox de lista única: o item ativo é apontado por id, e o
            // leitor de tela acompanha as setas sem mover o foco do campo.
            role="combobox"
            aria-expanded="true"
            aria-controls="paleta-resultados"
            aria-activedescendant={itens[foco] ? `paleta-item-${itens[foco].chave}` : undefined}
            autoComplete="off"
          />
          <kbd>ESC</kbd>
        </label>

        <div className="paleta-resultados" id="paleta-resultados" role="listbox">
          {rotasFiltradas.length > 0 && <div className="paleta-rotulo">NAVEGAÇÃO</div>}
          {rotasFiltradas.map((r, i) => (
            <button
              key={r.caminho}
              id={`paleta-item-${r.caminho}`}
              type="button"
              role="option"
              aria-selected={foco === i}
              className={`paleta-item${foco === i ? " focado" : ""}`}
              onMouseEnter={() => setFoco(i)}
              onClick={() => acionar(i)}
            >
              <Icone nome={r.icone} />
              <span>{r.rotulo}</span>
              <small>Abrir módulo</small>
            </button>
          ))}

          {eventosFiltrados.length > 0 && <div className="paleta-rotulo">EVENTOS</div>}
          {eventosFiltrados.map((e, i) => {
            const idx = rotasFiltradas.length + i;
            return (
              <button
                key={e.id}
                id={`paleta-item-${e.id}`}
                type="button"
                role="option"
                aria-selected={foco === idx}
                className={`paleta-item${foco === idx ? " focado" : ""}`}
                onMouseEnter={() => setFoco(idx)}
                onClick={() => acionar(idx)}
              >
                <i className={`ponto ${e.severidade}`} aria-hidden="true" />
                <span>{e.titulo}</span>
                {/* Severidade nunca sem a grandeza que a originou — vale aqui também. */}
                <small>
                  M {numero(e.magnitude, 1)} · {ROTULO_SEVERIDADE[e.severidade]} ·{" "}
                  {e.lugar ?? "local não informado"} · {instante(e.ocorrido_em)}
                </small>
              </button>
            );
          })}

          {!itens.length && (
            <p className="paleta-vazio">Nada encontrado para “{termo}”.</p>
          )}
        </div>
      </div>
    </>
  );
}
