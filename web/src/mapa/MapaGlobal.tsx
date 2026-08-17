import maplibregl, { type Map as MapaLibre, Marker, NavigationControl } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { listarEventos, usePeriodico } from "../dados/api";
import { carregarPaises } from "../dados/carregar";
import { aoTrocarTema } from "../tema";
import {
  ROTULO_SEVERIDADE,
  SEVERIDADES,
  type EventoResumo,
  type Severidade,
} from "../tipos";
import { CartaoEvento } from "./CartaoEvento";
import { estiloDoMapa } from "./estilo";

const rotuloDoMarcador = (e: EventoResumo): string =>
  `${e.titulo}, ${e.lugar ?? "local não informado"}. ${ROTULO_SEVERIDADE[e.severidade]}. ` +
  `${e.metrica_rotulo} ${e.magnitude ?? "não informada"}.`;

/** Marcadores são elementos DOM, não camada de símbolo: evita servidor de glifos
 *  e deixa a pulsação e o foco de teclado no CSS, como no protótipo. */
function elementoDoMarcador(e: EventoResumo, selecionado: boolean): HTMLButtonElement {
  const b = document.createElement("button");
  b.className = `marcador ${e.severidade}`;
  b.type = "button";
  b.setAttribute("aria-pressed", String(selecionado));
  b.setAttribute("aria-label", rotuloDoMarcador(e));
  b.title = `${e.titulo} — ${e.lugar ?? ""}`.trim();
  // Chave única para verificação e depuração. O `title` não serve: numa sequência
  // de tremores secundários vários eventos têm título idêntico.
  b.dataset.id = e.id;
  return b;
}

export function MapaGlobal() {
  const container = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaLibre | null>(null);
  const marcadores = useRef<Marker[]>([]);

  const [ocultas, setOcultas] = useState<Set<Severidade>>(new Set());
  const [selecionado, setSelecionado] = useState<EventoResumo | null>(null);
  const [erroMapa, setErroMapa] = useState<string | null>(null);
  const [pronto, setPronto] = useState(false);

  // Dado real do back-end, revalidado na cadência de coleta do USGS.
  const pagina = usePeriodico(() => listarEventos({ horas: 24, magnitudeMinima: 2.5 }));
  const eventos = pagina.dado?.itens ?? [];

  const visiveis = useMemo(
    () => eventos.filter((e) => !ocultas.has(e.severidade)),
    [eventos, ocultas],
  );

  // ── criação do mapa, uma vez ──────────────────────────────────────────
  useEffect(() => {
    if (!container.current) return;
    let vivo = true;
    let m: MapaLibre | null = null;

    (async () => {
      try {
        const paises = await carregarPaises();
        if (!vivo || !container.current) return;

        // Sem realce de país: a API entrega lat/lon, não o ISO do país. Atribuir
        // evento a país exige join espacial no PostGIS contra uma tabela de
        // países — vale fazer no back-end, não adivinhar no navegador.
        m = new maplibregl.Map({
          container: container.current,
          style: estiloDoMapa(paises, []),
          center: [10, 22],
          zoom: 1.1,
          minZoom: 0.6,
          maxZoom: 12,
          attributionControl: false,
          // NÃO usar `maxBounds`: longitude fora de ±180 é envolvida pelo MapLibre
          // e vira uma faixa estreita, para a qual ele aproxima. Ver histórico.
        });
        m.addControl(new NavigationControl({ showCompass: false }), "top-right");

        // Falha de estilo é assíncrona e emitida como evento, não lançada. Sem
        // isto, o mapa fica em branco sem nenhuma mensagem.
        m.on("error", (ev) => {
          if (vivo) setErroMapa(ev.error?.message ?? "erro desconhecido do MapLibre");
        });

        const criado = m;
        criado.on("load", () => {
          if (!vivo) return;
          criado.fitBounds(
            [
              [-180, -56],
              [180, 84],
            ],
            { padding: 8, animate: false },
          );
          setPronto(true);
        });

        mapa.current = m;
        if (import.meta.env.DEV) {
          (window as unknown as { __mapa?: MapaLibre }).__mapa = m;
        }
      } catch (e) {
        if (vivo) setErroMapa(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      vivo = false;
      m?.remove();
      mapa.current = null;
    };
  }, []);

  useEffect(
    () =>
      aoTrocarTema(async () => {
        const m = mapa.current;
        if (!m) return;
        m.setStyle(estiloDoMapa(await carregarPaises(), []));
      }),
    [],
  );

  // ── marcadores ────────────────────────────────────────────────────────
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;

    for (const mk of marcadores.current) mk.remove();
    marcadores.current = visiveis.map((e) => {
      const el = elementoDoMarcador(e, selecionado?.id === e.id);
      el.addEventListener("click", () => setSelecionado(e));
      const mk = new Marker({ element: el }).setLngLat([e.lon, e.lat]).addTo(m);
      // O MapLibre sobrescreve o aria-label com "Map marker" na construção.
      el.setAttribute("aria-label", rotuloDoMarcador(e));
      return mk;
    });

    return () => {
      for (const mk of marcadores.current) mk.remove();
      marcadores.current = [];
    };
  }, [visiveis, selecionado, pronto]);

  function alternar(s: Severidade) {
    setOcultas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(s)) proximo.delete(s);
      else proximo.add(s);
      return proximo;
    });
  }

  if (erroMapa) {
    return (
      <div className="vazio">
        <h2>Não foi possível carregar o mapa</h2>
        <p>{erroMapa}</p>
      </div>
    );
  }

  return (
    <div className="mapa-raiz">
      <div ref={container} className="mapa-canvas" />

      <div className="flutuante contador">
        <i className="ponto" />
        <b>{visiveis.length}</b> de {pagina.dado?.total ?? 0} sismos · 24 h
        {pagina.erro && <span className="alerta-inline">rede instável</span>}
      </div>

      <div className="flutuante legenda" role="group" aria-label="Filtrar por severidade">
        {SEVERIDADES.map((s) => (
          <button key={s} type="button" aria-pressed={!ocultas.has(s)} onClick={() => alternar(s)}>
            <i className={`ponto ${s}`} />
            {ROTULO_SEVERIDADE[s]}
            <b>{eventos.filter((e) => e.severidade === s).length}</b>
          </button>
        ))}
      </div>

      {selecionado && (
        <CartaoEvento evento={selecionado} aoFechar={() => setSelecionado(null)} />
      )}
    </div>
  );
}
