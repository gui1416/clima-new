import maplibregl, { type Map as MapaLibre, Marker, NavigationControl } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { carregarEventosDemo, carregarPaises } from "../dados/carregar";
import { aoTrocarTema } from "../tema";
import { ROTULO_SEVERIDADE, SEVERIDADES, type Evento, type Severidade } from "../tipos";
import { estiloDoMapa } from "./estilo";

/** Marcadores são elementos DOM, não camada de símbolo: evita servidor de glifos
 *  e deixa a pulsação e o foco de teclado no CSS, como no protótipo. */
function elementoDoMarcador(e: Evento, selecionado: boolean): HTMLButtonElement {
  const b = document.createElement("button");
  b.className = `marcador ${e.severity}`;
  b.type = "button";
  b.setAttribute("aria-pressed", String(selecionado));
  b.setAttribute(
    "aria-label",
    `${e.title}, ${e.place}, ${e.country}. ${e.severityLabel}. ${e.metric} ${e.metricLabel}.`,
  );
  b.title = `${e.title} — ${e.place}`;
  return b;
}

export function MapaGlobal() {
  const container = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaLibre | null>(null);
  const marcadores = useRef<Marker[]>([]);

  const [eventos, setEventos] = useState<Evento[]>([]);
  const [ocultas, setOcultas] = useState<Set<Severidade>>(new Set());
  const [selecionado, setSelecionado] = useState<Evento | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [pronto, setPronto] = useState(false);

  // useMemo é necessário, não cosmético: `visiveis` é dependência do efeito que
  // cria os marcadores. Um array novo a cada render recriaria todos os marcadores
  // em laço infinito.
  const visiveis = useMemo(
    () => eventos.filter((e) => !ocultas.has(e.severity)),
    [eventos, ocultas],
  );

  // ── criação do mapa, uma vez ──────────────────────────────────────────
  useEffect(() => {
    if (!container.current) return;
    let vivo = true;
    let m: MapaLibre | null = null;

    (async () => {
      try {
        const [paises, evts] = await Promise.all([carregarPaises(), carregarEventosDemo()]);
        if (!vivo || !container.current) return;

        const isos = [...new Set(evts.map((e) => e.countryId))];
        m = new maplibregl.Map({
          container: container.current,
          style: estiloDoMapa(paises, isos),
          center: [10, 22],
          zoom: 1.1,
          minZoom: 0.6,
          maxZoom: 12,
          attributionControl: false,
          // A geometria para em -57° de latitude (a Antártida não está no dado do
          // protótipo); deixar rolar além disso mostraria oceano vazio.
          maxBounds: [
            [-200, -62],
            [200, 86],
          ],
        });
        m.addControl(new NavigationControl({ showCompass: false }), "top-right");
        m.on("load", () => vivo && setPronto(true));
        mapa.current = m;
        setEventos(evts);
      } catch (e) {
        if (vivo) setErro(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      vivo = false;
      m?.remove();
      mapa.current = null;
    };
  }, []);

  // ── troca de tema: o estilo carrega as cores dos tokens ───────────────
  useEffect(
    () =>
      aoTrocarTema(async () => {
        const m = mapa.current;
        if (!m) return;
        const paises = await carregarPaises();
        const isos = [...new Set(eventos.map((e) => e.countryId))];
        m.setStyle(estiloDoMapa(paises, isos));
      }),
    [eventos],
  );

  // ── marcadores, refeitos quando a filtragem ou a seleção mudam ────────
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;

    for (const mk of marcadores.current) mk.remove();
    marcadores.current = visiveis.map((e) => {
      const el = elementoDoMarcador(e, selecionado?.id === e.id);
      el.addEventListener("click", () => setSelecionado(e));
      return new Marker({ element: el }).setLngLat([e.lon, e.lat]).addTo(m);
    });

    return () => {
      for (const mk of marcadores.current) mk.remove();
      marcadores.current = [];
    };
  }, [visiveis, selecionado, pronto]);

  // ── contorno do país do evento selecionado ────────────────────────────
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto || !m.getLayer("terra-selecionada")) return;
    m.setFilter("terra-selecionada", ["==", ["get", "iso"], selecionado?.countryId ?? ""]);
  }, [selecionado, pronto]);

  function alternar(s: Severidade) {
    setOcultas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(s)) proximo.delete(s);
      else proximo.add(s);
      return proximo;
    });
  }

  if (erro) {
    return (
      <div className="vazio">
        <h2>Não foi possível carregar o mapa</h2>
        <p>{erro}</p>
        <p>
          Se os dados estáticos estiverem faltando, gere-os a partir do protótipo com{" "}
          <code>npm run dados</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="mapa-raiz">
      <div ref={container} className="mapa-canvas" />

      <div className="flutuante contador">
        <i className="ponto" />
        <b>{visiveis.length}</b> de {eventos.length} eventos
      </div>

      <div className="flutuante legenda" role="group" aria-label="Filtrar por severidade">
        {SEVERIDADES.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={!ocultas.has(s)}
            onClick={() => alternar(s)}
          >
            <i className={`ponto ${s}`} />
            {ROTULO_SEVERIDADE[s]}
            <b>{eventos.filter((e) => e.severity === s).length}</b>
          </button>
        ))}
      </div>

      {selecionado && <CartaoEvento evento={selecionado} aoFechar={() => setSelecionado(null)} />}
    </div>
  );
}

function CartaoEvento({ evento, aoFechar }: { evento: Evento; aoFechar: () => void }) {
  return (
    <aside className="flutuante cartao-evento" aria-label={`Detalhes de ${evento.title}`}>
      <header>
        <i className={`ponto ${evento.severity}`} />
        {evento.severityLabel} · {evento.type}
        <span className="espacador" />
        <button type="button" className="btn-icone" onClick={aoFechar} aria-label="Fechar">
          ×
        </button>
      </header>

      <h2>{evento.title}</h2>
      <p className="local">
        {evento.place}, {evento.country} · {evento.time}
      </p>
      <p>{evento.summary}</p>

      {/* A métrica física nunca aparece sozinha nem escondida: severidade sem a
          grandeza que a originou é o erro que o produto existe para não cometer. */}
      <div className="metricas">
        <div className="metrica">
          <span>{evento.metricLabel.toUpperCase()}</span>
          <strong>{evento.metric}</strong>
        </div>
        <div className="metrica">
          <span>POPULAÇÃO EXPOSTA</span>
          <strong>{evento.people}</strong>
        </div>
        <div className="metrica">
          <span>FONTES QUE CONFIRMAM</span>
          <strong>{evento.sources}</strong>
        </div>
        <div className="metrica">
          <span>CONFIANÇA</span>
          <strong>{evento.confidence}%</strong>
        </div>
      </div>

      <div className="fontes">
        {evento.sourceNames.map((n) => (
          <span key={n}>{n}</span>
        ))}
      </div>
    </aside>
  );
}
