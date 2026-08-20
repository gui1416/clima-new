import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";

import {
  ROTAS,
  TelaAlertas,
  TelaEventos,
  TelaFontes,
  TelaMapa,
  TelaRelatorios,
  TelaVisaoGeral,
} from "./rotas";
import { Icone, SpriteIcones } from "./componentes/Icones";
import { PaletaComandos } from "./componentes/PaletaComandos";
import { buscarEstatisticas, buscarSaude, useFluxoDeEventos, usePeriodico } from "./dados/api";
import { inteiro } from "./formato";
import { alternarTema, temaAtual } from "./tema";

const GRUPOS = [
  { id: "monitoramento", rotulo: "MONITORAMENTO" },
  { id: "distribuicao", rotulo: "DISTRIBUIÇÃO" },
] as const;

/** Estado da coleta no rodapé da barra lateral.
 *
 * O lugar que no protótipo trazia um perfil de usuário fictício. Não há
 * autenticação no produto, e inventar "Guilherme · Administrador" seria dado
 * falso não declarado como falso — o que o CLAUDE.md proíbe. O que existe de
 * verdadeiro para ocupar esse canto é `/saude`: lacuna de coleta, fonte
 * silenciosa e fila de análise parada. É também a informação que mais importa
 * ver sem procurar, porque todas as outras telas mentem em silêncio quando ela
 * está ruim.
 */
function EstadoDaColeta() {
  const saude = usePeriodico(buscarSaude);
  const s = saude.dado;
  const papel = !s ? "inerte" : s.saudavel ? "ok" : "atencao";
  // Fontes distintas, não linhas de lacuna. O GDACS sozinho produz uma lacuna a
  // cada ciclo de coleta: contar linhas dizia "8 fontes com problema" num
  // catálogo de 8 fontes, das quais uma só estava de fato falhando.
  const afetadas = s
    ? new Set([...s.lacunas.map((l) => l.source_id), ...s.silenciosas]).size
    : 0;

  const detalhe = !s
    ? "consultando…"
    : s.saudavel
      ? `${inteiro(s.payloads_aguardando_analise)} na fila de análise`
      : afetadas
        ? `${afetadas} ${afetadas === 1 ? "fonte afetada" : "fontes afetadas"}`
        : "fila de análise atrasada";

  return (
    <NavLink to="/fontes" className={`estado-coleta estado-${papel}`}>
      <Icone nome="shield" tamanho="sm" />
      <span>
        <strong>{!s ? "Coleta" : s.saudavel ? "Coleta íntegra" : "Coleta com falha"}</strong>
        <small>{detalhe}</small>
      </span>
      <i aria-hidden="true" />
    </NavLink>
  );
}

export function App() {
  const [tema, setTema] = useState(temaAtual);
  const [menuAberto, setMenuAberto] = useState(false);
  const [paletaAberta, setPaletaAberta] = useState(false);
  const { pathname } = useLocation();
  const rota = ROTAS.find((r) => r.caminho === pathname);

  // O fluxo diz quando algo mudou; a pílula diz se ele está de pé. "AO VIVO"
  // escrito à mão sobre um socket caído é a mentira mais fácil de cometer aqui.
  const fluxo = useFluxoDeEventos();
  // A pílula precisa vir do dado. Escrita à mão, ela dizia "1 fonte · sem
  // deduplicação" depois de o EMSC entrar e o motor já ter unido 7 eventos — texto
  // fixo sobre estado que muda é mentira com data de validade.
  const est = usePeriodico(() => buscarEstatisticas(24, 0), [fluxo.revisao]);

  useEffect(() => setMenuAberto(false), [pathname]);

  const alternarPaleta = useCallback(() => setPaletaAberta((v) => !v), []);

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        alternarPaleta();
      }
      if (e.key === "Escape") {
        setPaletaAberta(false);
        setMenuAberto(false);
      }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [alternarPaleta]);

  const contagem: Record<string, number | undefined> = {
    "/eventos": est.dado?.eventos_total,
    "/fontes": est.dado?.fontes_ativas,
  };

  return (
    <div className="app">
      <SpriteIcones />

      <nav className={`sidebar${menuAberto ? " aberto" : ""}`} aria-label="Navegação principal">
        <div className="marca">
          <span className="marca-selo" aria-hidden="true">
            GRM
          </span>
          <span className="marca-texto">
            <strong>Clima Global</strong>
            <small>Intelligence</small>
          </span>
          <button
            type="button"
            className="btn-icone fechar-menu"
            onClick={() => setMenuAberto(false)}
            aria-label="Fechar navegação"
          >
            <Icone nome="close" tamanho="sm" />
          </button>
        </div>

        <div className="nav-rolagem">
          {GRUPOS.map((g) => (
            <div key={g.id}>
              <div className="nav-rotulo">{g.rotulo}</div>
              {ROTAS.filter((r) => r.grupo === g.id).map((r) => (
                <NavLink key={r.caminho} to={r.caminho} className="nav-item">
                  <Icone nome={r.icone} />
                  <span>{r.rotulo}</span>
                  {contagem[r.caminho] !== undefined && (
                    <em className="nav-conta">{inteiro(contagem[r.caminho])}</em>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </div>

        <div className="sidebar-rodape">
          <EstadoDaColeta />
        </div>
      </nav>

      {menuAberto && (
        <button
          type="button"
          className="scrim-menu"
          onClick={() => setMenuAberto(false)}
          aria-label="Fechar navegação"
        />
      )}

      <div className="area">
        <header className="topbar">
          <div className="topo-esquerda">
            <button
              type="button"
              className="btn-icone abrir-menu"
              onClick={() => setMenuAberto(true)}
              aria-label="Abrir navegação"
              aria-expanded={menuAberto}
            >
              <Icone nome="menu" />
            </button>
            <div className="trilha">
              <span>CLIMA GLOBAL /</span>
              <strong>{rota?.rotulo ?? "Clima Global"}</strong>
            </div>
          </div>

          <div className="topo-acoes">
            {/* Três estados reais, não dois: conectando, ao vivo e caído. O
                terceiro é o que importa — sem ele, socket morto lê como ao vivo. */}
            <span className={`pilula-fluxo fluxo-${fluxo.estado}`} title={est.dado?.aviso ?? undefined}>
              <i className="ponto" />
              <span className="pilula-texto">
                {fluxo.estado === "ao-vivo"
                  ? "FLUXO AO VIVO"
                  : fluxo.estado === "conectando"
                    ? "CONECTANDO"
                    : "SEM FLUXO · 60 S"}
              </span>
            </span>

            <span className="pilula-fontes" title={est.dado?.aviso ?? undefined}>
              {est.dado
                ? `${est.dado.fontes_ativas} fontes · ${est.dado.eventos_multifonte} com 2+`
                : "carregando…"}
            </span>

            <button type="button" className="abrir-busca" onClick={alternarPaleta}>
              <Icone nome="search" tamanho="sm" />
              <span>Buscar evento ou módulo</span>
              <kbd>⌘ K</kbd>
            </button>

            <button
              type="button"
              className="btn-icone buscar-compacto"
              onClick={alternarPaleta}
              aria-label="Buscar evento ou módulo"
            >
              <Icone nome="search" />
            </button>

            <button
              type="button"
              className="btn-icone"
              onClick={() => setTema(alternarTema())}
              aria-label={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
            >
              <Icone nome={tema === "dark" ? "moon" : "sun"} />
            </button>
          </div>
        </header>

        <main className={rota?.telaCheia ? "conteudo sem-rolagem" : "conteudo"}>
          <Routes>
            <Route path="/" element={<Navigate to="/visao-geral" replace />} />
            <Route path="/visao-geral" element={<TelaVisaoGeral />} />
            <Route path="/mapa" element={<TelaMapa />} />
            <Route path="/eventos" element={<TelaEventos />} />
            <Route path="/fontes" element={<TelaFontes />} />
            <Route path="/alertas" element={<TelaAlertas />} />
            <Route path="/relatorios" element={<TelaRelatorios />} />
            <Route path="*" element={<Navigate to="/visao-geral" replace />} />
          </Routes>
        </main>
      </div>

      <PaletaComandos
        aberta={paletaAberta}
        aoFechar={() => setPaletaAberta(false)}
        rotas={ROTAS}
      />
    </div>
  );
}
