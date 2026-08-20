import maplibregl, { type Map as MapaLibre, Marker } from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Icone } from "../componentes/Icones";
import { detalharEvento, listarEventos, useFluxoDeEventos, usePeriodico } from "../dados/api";
import { carregarPaises } from "../dados/carregar";
import { instante, numero, relogio } from "../formato";
import { aoTrocarTema } from "../tema";
import {
  ROTULO_SEVERIDADE,
  SEVERIDADES,
  type EventoResumo,
  type Severidade,
} from "../tipos";
import { CartaoEvento } from "./CartaoEvento";
import { IMAGEM_PONTOS, estiloDoMapa, padraoDePontos, type BaseDoMapa } from "./estilo";

const BASES: ReadonlyArray<{ id: BaseDoMapa; rotulo: string }> = [
  { id: "pontilhado", rotulo: "Pontilhado" },
  { id: "contorno", rotulo: "Contorno" },
  { id: "solido", rotulo: "Sólido" },
];

const semAnimacao = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const rotuloDoMarcador = (e: EventoResumo): string =>
  `${e.titulo}, ${e.lugar ?? "local não informado"}. ${ROTULO_SEVERIDADE[e.severidade]}. ` +
  `${e.metrica_rotulo} ${e.magnitude ?? "não informada"}.`;

/** Marcadores são elementos DOM, não camada de símbolo: evita servidor de glifos
 *  e deixa a pulsação e o foco de teclado no CSS, como no protótipo. */
function elementoDoMarcador(e: EventoResumo, selecionado: boolean): HTMLButtonElement {
  const b = document.createElement("button");
  b.className = `marcador ${e.severidade}${e.fontes_confirmando > 1 ? " multifonte" : ""}`;
  b.type = "button";
  b.setAttribute("aria-pressed", String(selecionado));
  b.setAttribute("aria-label", rotuloDoMarcador(e));
  b.title = `${e.titulo} — ${e.lugar ?? ""}`.trim();
  // Chave única para verificação e depuração. O `title` não serve: numa sequência
  // de tremores secundários vários eventos têm título idêntico.
  b.dataset.id = e.id;
  const tamanho = Math.max(16, Math.min(30, 13 + (e.magnitude ?? 2.5) * 2.2));
  b.style.setProperty("--tamanho-marcador", `${tamanho}px`);
  const tooltip = document.createElement("span");
  tooltip.className = "marcador-tooltip";
  const destaque = document.createElement("b");
  destaque.textContent = `M ${numero(e.magnitude, 1)} · ${ROTULO_SEVERIDADE[e.severidade]}`;
  const lugar = document.createElement("span");
  lugar.textContent = e.lugar ?? "Local não informado";
  const contexto = document.createElement("small");
  contexto.textContent = `${instante(e.ocorrido_em)} · ${e.fontes_confirmando} ${e.fontes_confirmando === 1 ? "fonte" : "fontes"}`;
  tooltip.append(destaque, lugar, contexto);
  b.append(tooltip);
  return b;
}

interface GrupoMapa {
  eventos: EventoResumo[];
  lon: number;
  lat: number;
}

/** Agrupa pela distância percebida na tela. Em zoom global, 44 px evita pilhas
 * ilegíveis; ao aproximar, o raio diminui e os eventos voltam a se separar. */
function agruparNaTela(mapa: MapaLibre, eventos: EventoResumo[]): GrupoMapa[] {
  const raio = mapa.getZoom() >= 7 ? 20 : mapa.getZoom() >= 4 ? 26 : mapa.getZoom() >= 2 ? 30 : 36;
  const pontos = eventos.map((evento) => ({ evento, p: mapa.project([evento.lon, evento.lat]) }));
  const grupos: Array<typeof pontos> = [];
  for (const ponto of pontos) {
    const proximo = grupos.find((grupo) => {
      const x = grupo.reduce((s, item) => s + item.p.x, 0) / grupo.length;
      const y = grupo.reduce((s, item) => s + item.p.y, 0) / grupo.length;
      return (ponto.p.x - x) ** 2 + (ponto.p.y - y) ** 2 <= raio ** 2;
    });
    if (proximo) proximo.push(ponto);
    else grupos.push([ponto]);
  }

  return grupos.map((grupo) => {
    const x = grupo.reduce((s, item) => s + item.p.x, 0) / grupo.length;
    const y = grupo.reduce((s, item) => s + item.p.y, 0) / grupo.length;
    const centro = mapa.unproject([x, y]);
    return { eventos: grupo.map((item) => item.evento), lon: centro.lng, lat: centro.lat };
  });
}

function elementoDoGrupo(grupo: GrupoMapa, selecionado: EventoResumo | null): HTMLButtonElement {
  const ordem: Record<Severidade, number> = { moderate: 0, high: 1, critical: 2 };
  const dominante = grupo.eventos.reduce((a, b) => ordem[a.severidade] >= ordem[b.severidade] ? a : b);
  const maior = Math.max(...grupo.eventos.map((e) => e.magnitude ?? 0));
  const b = document.createElement("button");
  b.type = "button";
  b.className = `marcador-cluster ${dominante.severidade}${grupo.eventos.some((e) => e.id === selecionado?.id) ? " selecionado" : ""}`;
  b.setAttribute("aria-label", `Grupo de ${grupo.eventos.length} sismos. Maior magnitude ${numero(maior, 1)}. Ative para aproximar.`);
  b.title = `${grupo.eventos.length} sismos agrupados · maior M ${numero(maior, 1)}`;
  const quantidade = document.createElement("span");
  quantidade.textContent = String(grupo.eventos.length);
  b.append(quantidade);
  return b;
}

/** Distância no chão coberta por 90 px na latitude do centro. */
function escalaDoMapa(mapa: MapaLibre): string {
  const y = mapa.getContainer().clientHeight / 2;
  const a = mapa.unproject([10, y]);
  const b = mapa.unproject([100, y]);
  const metros = a.distanceTo(b);
  if (metros >= 1_000_000) return `${numero(metros / 1_000_000, 1)} mil km`;
  if (metros >= 1000) return `${numero(metros / 1000, 0)} km`;
  return `${numero(metros, 0)} m`;
}

/**
 * Zoom mínimo que ainda deixa o mundo inteiro caber na largura do contêiner.
 *
 * Havia um `minZoom: 0.6` fixo, e ele quebrava exatamente onde mais importa: num
 * contêiner de 336 px o mundo em z=0,6 tem 776 px, então o `fitBounds` inicial
 * batia no piso e o mapa abria no celular mostrando 40% do planeta — com o
 * usuário sem como afastar. O piso agora é medido, não escolhido.
 */
function ajustarZoomMinimo(m: MapaLibre): void {
  const largura = m.getContainer().clientWidth;
  if (!largura) return;
  // 512 px é a largura do mundo em z=0 na projeção do MapLibre.
  const cabe = Math.log2(largura / 512);
  m.setMinZoom(Math.max(0, Math.min(0.6, cabe)));
}

const normalizar = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

export function MapaGlobal() {
  const container = useRef<HTMLDivElement>(null);
  const raiz = useRef<HTMLElement>(null);
  const mapa = useRef<MapaLibre | null>(null);
  const marcadores = useRef<Marker[]>([]);

  const [parametros, setParametros] = useSearchParams();
  const [ocultas, setOcultas] = useState<Set<Severidade>>(new Set());
  const [horas, setHoras] = useState(24);
  const [soMultifonte, setSoMultifonte] = useState(false);
  const [termo, setTermo] = useState("");
  const [resumoAberto, setResumoAberto] = useState(false);
  const [selecionado, setSelecionado] = useState<EventoResumo | null>(null);
  const [erroMapa, setErroMapa] = useState<string | null>(null);
  // Evento que chegou por `?evento=` e não está na consulta atual do mapa — ver
  // o efeito de deep link.
  const [avulso, setAvulso] = useState<EventoResumo | null>(null);
  const [pronto, setPronto] = useState(false);
  const [revisaoMapa, setRevisaoMapa] = useState(0);

  // Camadas ligáveis do protótipo, com o mesmo vocabulário.
  const [base, setBase] = useState<BaseDoMapa>("pontilhado");
  const [comGrade, setComGrade] = useState(true);
  const [agrupar, setAgrupar] = useState(true);
  const [camadasAbertas, setCamadasAbertas] = useState(false);
  const [emTelaCheia, setEmTelaCheia] = useState(false);
  const [leitura, setLeitura] = useState({ escala: "—", lat: "—", lon: "—", zoom: "1,0" });

  const fluxo = useFluxoDeEventos();
  // Dado real do back-end. `fontes_minimas` é filtro do servidor, não recorte no
  // navegador: pedir só o multifonte reduz a resposta e é a consulta que expõe o
  // resultado do motor de correlação.
  const pagina = usePeriodico(
    () => listarEventos({ horas, magnitudeMinima: 2.5, fontesMinimas: soMultifonte ? 2 : 0 }),
    [horas, soMultifonte, fluxo.revisao],
  );
  const eventos = useMemo(() => {
    const base = pagina.dado?.itens ?? [];
    // O evento vindo de link direto entra na lista mesmo fora do recorte atual.
    // Sem isso ele abriria a gaveta sem marcador correspondente no mapa.
    if (!avulso || base.some((e) => e.id === avulso.id)) return base;
    return [avulso, ...base];
  }, [pagina.dado, avulso]);

  const q = normalizar(termo.trim());
  const visiveis = useMemo(
    () =>
      eventos.filter(
        (e) =>
          !ocultas.has(e.severidade) &&
          (!q || normalizar(`${e.titulo} ${e.lugar ?? ""}`).includes(q)),
      ),
    [eventos, ocultas, q],
  );
  const maisForte = useMemo(
    () => visiveis.reduce<EventoResumo | null>((maior, e) =>
      !maior || (e.magnitude ?? -Infinity) > (maior.magnitude ?? -Infinity) ? e : maior, null),
    [visiveis],
  );
  const multifonte = visiveis.filter((e) => e.fontes_confirmando > 1).length;
  const grupos = useMemo(() => {
    const m = mapa.current;
    if (!m || !pronto) return [];
    return agrupar
      ? agruparNaTela(m, visiveis)
      : visiveis.map((e) => ({ eventos: [e], lon: e.lon, lat: e.lat }));
    // `revisaoMapa` é a dependência de viewport: pan/zoom mudam o agrupamento
    // sem mudar a lista.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visiveis, pronto, revisaoMapa, agrupar]);

  /** Os que estão de fato no enquadramento — o rótulo da faixa diz isso, e antes
   *  ele mentia: a lista mostrava os 12 primeiros de todo o mundo mesmo com o
   *  mapa aproximado num continente. O recorte é local porque o dado já está no
   *  navegador; mandar `bbox` ao servidor a cada pan pagaria uma ida de rede
   *  para filtrar o que já está em memória. */
  const noEnquadramento = useMemo(() => {
    const m = mapa.current;
    if (!m || !pronto) return visiveis;
    const limites = m.getBounds();
    return visiveis.filter((e) => limites.contains([e.lon, e.lat]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visiveis, pronto, revisaoMapa]);

  const atualizarLeitura = useCallback((m: MapaLibre) => {
    const c = m.getCenter();
    setLeitura({
      escala: escalaDoMapa(m),
      lat: `${numero(c.lat, 1)}°`,
      lon: `${numero(c.lng, 1)}°`,
      zoom: numero(m.getZoom(), 1),
    });
  }, []);

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
          style: estiloDoMapa(paises, { base: "pontilhado", grade: true }),
          center: [10, 22],
          zoom: 1.1,
          maxZoom: 12,
          attributionControl: false,
          // NÃO usar `maxBounds`: longitude fora de ±180 é envolvida pelo MapLibre
          // e vira uma faixa estreita, para a qual ele aproxima. Ver histórico.
        });

        // O padrão pontilhado só existe como bitmap, e `setStyle` descarta as
        // imagens registradas. Este é o gancho que o MapLibre emite quando uma
        // camada referencia imagem ausente — responder aqui é o que impede o erro
        // de console a cada troca de base ou de tema.
        m.on("styleimagemissing", (ev) => {
          const atual = mapa.current;
          if (!atual || ev.id !== IMAGEM_PONTOS || atual.hasImage(IMAGEM_PONTOS)) return;
          atual.addImage(IMAGEM_PONTOS, padraoDePontos(), { pixelRatio: 2 });
        });

        // Falha de estilo é assíncrona e emitida como evento, não lançada. Sem
        // isto, o mapa fica em branco sem nenhuma mensagem.
        m.on("error", (ev) => {
          if (vivo) setErroMapa(ev.error?.message ?? "erro desconhecido do MapLibre");
        });

        const criado = m;
        criado.on("load", () => {
          if (!vivo) return;
          ajustarZoomMinimo(criado);
          criado.fitBounds(
            [
              [-180, -56],
              [180, 84],
            ],
            { padding: 8, animate: false },
          );
          setPronto(true);
          atualizarLeitura(criado);
        });
        const reagrupar = () => {
          setRevisaoMapa((v) => v + 1);
          atualizarLeitura(criado);
        };
        // Girar o aparelho ou abrir o painel muda a largura, e com ela o piso.
        criado.on("resize", () => ajustarZoomMinimo(criado));
        criado.on("zoomend", reagrupar);
        criado.on("moveend", reagrupar);
        criado.on("resize", reagrupar);

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
  }, [atualizarLeitura]);

  // ── base e grade: reconstroem o estilo ────────────────────────────────
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;
    let vivo = true;
    void carregarPaises().then((paises) => {
      if (vivo && mapa.current) mapa.current.setStyle(estiloDoMapa(paises, { base, grade: comGrade }));
    });
    return () => {
      vivo = false;
    };
  }, [base, comGrade, pronto]);

  useEffect(
    () =>
      aoTrocarTema(async () => {
        const m = mapa.current;
        if (!m) return;
        // O padrão é gerado na tinta do tema; sem remover, o pontilhado ficaria
        // com a cor do tema anterior até um recarregamento.
        if (m.hasImage(IMAGEM_PONTOS)) m.removeImage(IMAGEM_PONTOS);
        m.setStyle(estiloDoMapa(await carregarPaises(), { base, grade: comGrade }));
      }),
    [base, comGrade],
  );

  // ── tela cheia ────────────────────────────────────────────────────────
  useEffect(() => {
    const aoMudar = () => {
      const cheia = document.fullscreenElement === raiz.current;
      setEmTelaCheia(cheia);
      // O canvas do MapLibre não acompanha a mudança de caixa sozinho.
      window.setTimeout(() => mapa.current?.resize(), 60);
    };
    document.addEventListener("fullscreenchange", aoMudar);
    return () => document.removeEventListener("fullscreenchange", aoMudar);
  }, []);

  // ── deep link `?evento=` (paleta de comandos, feed, tabela) ────────────
  //
  // Quem envia o link busca numa janela mais larga que a do mapa: a paleta
  // consulta 72 h sem piso de magnitude, e a tabela de eventos idem. Um sismo
  // M 1,2 de anteontem existe lá e não está na consulta de 24 h / M 2,5 daqui —
  // e a primeira versão simplesmente não fazia nada nesse caso, deixando o
  // usuário num mapa sem explicação. Quando o id não está na lista, ele é
  // buscado por `/api/eventos/{id}` e entra como avulso.
  useEffect(() => {
    const id = parametros.get("evento");
    if (!id || !pronto) return;

    const consumir = () => {
      // Mantê-lo faria a seleção voltar a cada revalidação, impedindo o usuário
      // de fechar o cartão.
      const proximos = new URLSearchParams(parametros);
      proximos.delete("evento");
      setParametros(proximos, { replace: true });
    };

    const aplicar = (alvo: EventoResumo) => {
      setSelecionado(alvo);
      mapa.current?.flyTo({
        center: [alvo.lon, alvo.lat],
        zoom: Math.max(mapa.current.getZoom(), 4.5),
        animate: !semAnimacao(),
      });
    };

    const local = eventos.find((e) => e.id === id);
    if (local) {
      aplicar(local);
      consumir();
      return;
    }
    // Espera a lista chegar antes de concluir que o evento não está nela.
    if (pagina.carregando) return;

    let vivo = true;
    detalharEvento(id)
      .then((d) => {
        if (!vivo) return;
        setAvulso(d);
        aplicar(d);
      })
      .catch(() => {
        // Id inexistente ou API fora: consumir o parâmetro do mesmo jeito, ou o
        // efeito tenta de novo a cada revalidação.
      })
      .finally(() => vivo && consumir());
    return () => {
      vivo = false;
    };
  }, [parametros, setParametros, pronto, eventos, pagina.carregando]);

  // ── marcadores ────────────────────────────────────────────────────────
  useEffect(() => {
    const m = mapa.current;
    if (!m || !pronto) return;

    for (const mk of marcadores.current) mk.remove();
    marcadores.current = grupos.map((grupo) => {
      if (grupo.eventos.length === 1) {
        const e = grupo.eventos[0]!;
        const el = elementoDoMarcador(e, selecionado?.id === e.id);
        el.addEventListener("click", () => setSelecionado(e));
        const mk = new Marker({ element: el }).setLngLat([e.lon, e.lat]).addTo(m);
        el.setAttribute("aria-label", rotuloDoMarcador(e));
        return mk;
      }

      const el = elementoDoGrupo(grupo, selecionado);
      el.addEventListener("click", () => {
        setSelecionado(null);
        m.easeTo({
          center: [grupo.lon, grupo.lat],
          zoom: Math.min(m.getZoom() + 2.2, m.getMaxZoom()),
          duration: semAnimacao() ? 0 : 420,
        });
      });
      const mk = new Marker({ element: el }).setLngLat([grupo.lon, grupo.lat]).addTo(m);
      el.setAttribute("aria-label", `Grupo de ${grupo.eventos.length} sismos. Ative para aproximar.`);
      return mk;
    });

    return () => {
      for (const mk of marcadores.current) mk.remove();
      marcadores.current = [];
    };
  }, [grupos, selecionado, pronto]);

  function alternar(s: Severidade) {
    setOcultas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(s)) proximo.delete(s);
      else proximo.add(s);
      return proximo;
    });
  }

  function destacar(e: EventoResumo) {
    setSelecionado(e);
    mapa.current?.flyTo({
      center: [e.lon, e.lat],
      zoom: Math.max(mapa.current.getZoom(), 4),
      animate: !semAnimacao(),
    });
  }

  const enquadrarMundo = () => {
    mapa.current?.fitBounds([[-180, -56], [180, 84]], { padding: 8, animate: !semAnimacao() });
  };

  const alternarTelaCheia = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void raiz.current?.requestFullscreen().catch(() => setEmTelaCheia(false));
  };

  if (erroMapa) {
    return (
      <div className="vazio">
        <h2>Não foi possível carregar o mapa</h2>
        <p>{erroMapa}</p>
      </div>
    );
  }

  return (
    <div className="mapa-pagina">
      <header className="cabecalho-tela cabecalho-mapa-pagina">
        <div className="cabecalho-tela-copy">
          <div className="linha-selo">
            <span className="selo-tela">MAPA OPERACIONAL</span>
            <span className="contexto-tela">
              {eventos.length} eventos monitorados · {noEnquadramento.length} no enquadramento
            </span>
          </div>
          <h2>Mapa global</h2>
          <p>Explore sismos, magnitude e evidências por localização.</p>
        </div>
        {maisForte && (
          <button type="button" className="acao-principal" onClick={() => destacar(maisForte)}>
            <Icone nome="crosshair" tamanho="sm" />
            Localizar maior magnitude
          </button>
        )}
      </header>

      <div className="layout-mapa-operacional">
        <aside className={`painel-mapa${resumoAberto ? " expandido" : ""}`} aria-label="Filtros e resumo do mapa">
          <header className="painel-mapa-cabecalho">
            <div>
              <span className="sobretitulo">REFINAR VISUALIZAÇÃO</span>
              <h2>Filtros</h2>
            </div>
            <span className={`estado-mapa${pagina.erro ? " com-erro" : ""}`}>
              <i /> {pagina.erro ? "desatualizado" : pagina.carregando ? "atualizando" : fluxo.estado === "ao-vivo" ? "ao vivo" : "atualizado"}
            </span>
          </header>

          <div className="mapa-kpis" aria-label="Indicadores dos eventos filtrados">
            <div><strong>{visiveis.length}</strong><span>visíveis</span></div>
            <div><strong>M {numero(maisForte?.magnitude, 1)}</strong><span>maior mag.</span></div>
            <div><strong>{multifonte}</strong><span>com 2+ fontes</span></div>
          </div>

          <button className="alternar-resumo" type="button" onClick={() => setResumoAberto((v) => !v)} aria-expanded={resumoAberto}>
            <Icone nome="filter" tamanho="sm" />
            {resumoAberto ? "Ocultar filtros" : "Filtros e legenda"}
          </button>

          <div className="mapa-controles">
            <div className="grupo-controle-mapa">
              <span>Janela de tempo</span>
              <div className="segmentado-mapa" role="group" aria-label="Janela de tempo do mapa">
                {[6, 24, 72].map((h) => <button key={h} type="button" aria-pressed={horas === h} onClick={() => setHoras(h)}>{h} h</button>)}
              </div>
            </div>

            <div className="grupo-controle-mapa">
              <span>Severidade · toque para filtrar</span>
              <div className="filtros-mapa" role="group" aria-label="Filtrar por severidade">
                {SEVERIDADES.map((s) => (
                  <button key={s} type="button" aria-pressed={!ocultas.has(s)} onClick={() => alternar(s)}>
                    <i className={`simbolo-severidade ${s}`} />
                    <span><b>{ROTULO_SEVERIDADE[s]}</b><small>{s === "critical" ? "M 6,0+" : s === "high" ? "M 4,5–5,9" : "M 2,5–4,4"}</small></span>
                    <strong>{eventos.filter((e) => e.severidade === s).length}</strong>
                  </button>
                ))}
              </div>
            </div>

            {/* O filtro do diferencial. Vai ao servidor como `fontes_minimas=2`. */}
            <button
              type="button"
              className={`chave-mapa${soMultifonte ? " ligada" : ""}`}
              role="switch"
              aria-checked={soMultifonte}
              onClick={() => setSoMultifonte((v) => !v)}
            >
              <span>
                <b>Só confirmados por 2+</b>
                <small>consulta o motor de correlação</small>
              </span>
              <i aria-hidden="true" />
            </button>

            <p className="ajuda-mapa"><i className="anel-multifonte" /> Anel duplo indica confirmação por duas ou mais fontes.</p>
            <p className="dica-mapa"><b>Como explorar</b><span>Clique em um marcador para abrir magnitude, profundidade e procedência.</span></p>
          </div>
        </aside>

        <section
          ref={raiz}
          className={`mapa-raiz${emTelaCheia ? " tela-cheia" : ""}`}
          aria-label={`Mapa mundial com ${visiveis.length} sismos visíveis`}
        >
          <div ref={container} className="mapa-canvas" />

          <div className="mapa-flutuante-topo-esquerda">
            <label className="busca-mapa">
              <Icone nome="search" tamanho="sm" />
              <input
                value={termo}
                onChange={(e) => setTermo(e.target.value)}
                placeholder="Buscar lugar ou evento no mapa"
                aria-label="Buscar lugar ou evento no mapa"
              />
              {termo && (
                <button type="button" onClick={() => setTermo("")} aria-label="Limpar busca do mapa">
                  <Icone nome="close" tamanho="sm" />
                </button>
              )}
            </label>
            <div className="flutuante badge-mapa">
              <i className="ponto" />
              <b>{visiveis.length}</b> eventos em {grupos.length} pontos · {relogio(pagina.atualizadoEm)}
            </div>
          </div>

          <div className="mapa-flutuante-topo-direita">
            <div className="abas-base" role="tablist" aria-label="Estilo do mapa">
              {BASES.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  role="tab"
                  aria-selected={base === b.id}
                  onClick={() => setBase(b.id)}
                >
                  {b.rotulo}
                </button>
              ))}
            </div>
            <div className="envolve-camadas">
              <button
                type="button"
                className="btn-mapa"
                aria-label="Camadas do mapa"
                aria-expanded={camadasAbertas}
                onClick={() => setCamadasAbertas((v) => !v)}
              >
                <Icone nome="layers" tamanho="sm" />
              </button>
              {camadasAbertas && (
                <div className="popover-camadas" role="group" aria-label="Camadas">
                  <button type="button" role="switch" aria-checked={comGrade} onClick={() => setComGrade((v) => !v)}>
                    <span>Grade de coordenadas</span>
                    <i aria-hidden="true" />
                  </button>
                  <button type="button" role="switch" aria-checked={agrupar} onClick={() => setAgrupar((v) => !v)}>
                    <span>Agrupar próximos</span>
                    <i aria-hidden="true" />
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="pilha-zoom">
            <button type="button" onClick={() => mapa.current?.zoomIn()} aria-label="Aproximar">
              <Icone nome="plus" tamanho="sm" />
            </button>
            <button type="button" onClick={() => mapa.current?.zoomOut()} aria-label="Afastar">
              <Icone nome="minus" tamanho="sm" />
            </button>
            <button type="button" onClick={enquadrarMundo} aria-label="Enquadrar o mundo">
              <Icone nome="crosshair" tamanho="sm" />
            </button>
            <button
              type="button"
              onClick={alternarTelaCheia}
              aria-label={emTelaCheia ? "Sair da tela cheia" : "Mapa em tela cheia"}
            >
              <Icone nome={emTelaCheia ? "shrink" : "expand"} tamanho="sm" />
            </button>
          </div>

          {/* Legenda e leitura de escala, como no protótipo: a cor sozinha nunca
              carrega significado, e o número ao lado é a mitigação exigida. */}
          <div className="flutuante legenda-mapa">
            {SEVERIDADES.map((s) => (
              <span key={s} className={ocultas.has(s) ? "apagada" : ""}>
                <i className={`ponto ${s}`} /> {ROTULO_SEVERIDADE[s]}
                <b>{visiveis.filter((e) => e.severidade === s).length}</b>
              </span>
            ))}
          </div>

          <div className="flutuante leitura-mapa">
            <span className="regua"><i /> {leitura.escala}</span>
            <span>LAT <b>{leitura.lat}</b></span>
            <span>LON <b>{leitura.lon}</b></span>
            <span>ZOOM <b>{leitura.zoom}×</b></span>
          </div>

          {selecionado && (
            <CartaoEvento evento={selecionado} aoFechar={() => setSelecionado(null)} />
          )}
        </section>

        <section className="faixa-eventos-mapa" aria-label="Eventos visíveis no mapa">
          <header>
            <h2>Eventos no enquadramento</h2>
            <span>{noEnquadramento.length} de {eventos.length} monitorados</span>
          </header>
          <div className="lista-eventos-mapa">
            {noEnquadramento.slice(0, 12).map((e) => (
              <button key={e.id} type="button" className={selecionado?.id === e.id ? "selecionado" : ""} onClick={() => destacar(e)}>
                <span className={`rotulo-evento-mapa ${e.severidade}`}><i className={`ponto ${e.severidade}`} />{ROTULO_SEVERIDADE[e.severidade]}</span>
                <strong>{e.titulo}</strong>
                <small>{e.lugar ?? "Local não informado"}</small>
                <span className="meta-evento-mapa"><b>M {numero(e.magnitude, 1)}</b> · {instante(e.ocorrido_em)} · {e.fontes_confirmando} {e.fontes_confirmando === 1 ? "fonte" : "fontes"}</span>
              </button>
            ))}
            {!noEnquadramento.length && (
              <p className="nota">Nenhum evento no enquadramento atual. Afaste o mapa ou amplie a janela.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
