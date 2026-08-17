import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useState } from "react";

import {
  ROTAS,
  TelaAlertas,
  TelaEventos,
  TelaFontes,
  TelaMapa,
  TelaRelatorios,
  TelaVisaoGeral,
} from "./rotas";
import { buscarEstatisticas, usePeriodico } from "./dados/api";
import { alternarTema, temaAtual } from "./tema";

const GRUPOS = [
  { id: "monitoramento", rotulo: "MONITORAMENTO" },
  { id: "distribuicao", rotulo: "DISTRIBUIÇÃO" },
] as const;

export function App() {
  const [tema, setTema] = useState(temaAtual);
  // A pílula precisa vir do dado. Escrita à mão, ela dizia "1 fonte · sem
  // deduplicação" depois de o EMSC entrar e o motor já ter unido 7 eventos — texto
  // fixo sobre estado que muda é mentira com data de validade.
  const est = usePeriodico(() => buscarEstatisticas(24, 0));
  const { pathname } = useLocation();
  const rota = ROTAS.find((r) => r.caminho === pathname);

  return (
    <div className="app">
      <nav className="sidebar" aria-label="Navegação principal">
        <div className="marca">
          <i aria-hidden="true" />
          Clima Global
        </div>

        {GRUPOS.map((g) => (
          <div key={g.id}>
            <div className="nav-rotulo">{g.rotulo}</div>
            {ROTAS.filter((r) => r.grupo === g.id).map((r) => (
              <NavLink key={r.caminho} to={r.caminho} className="nav-item">
                <span aria-hidden="true">{r.icone}</span>
                {r.rotulo}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="area">
        <header className="topbar">
          <h1>{rota?.rotulo ?? "Clima Global"}</h1>
          <span className="espacador" />

          {/* Descreve o que existe, sem prometer "ao vivo": a cadência é de 60 s. */}
          <span className="pilula" title={est.dado?.aviso ?? undefined}>
            <i className="ponto" />
            {est.dado
              ? `${est.dado.fontes_ativas} fontes · ${est.dado.eventos_multifonte} eventos com 2+`
              : "carregando…"}
          </span>

          <button
            type="button"
            className="btn-icone"
            onClick={() => setTema(alternarTema())}
            aria-label={tema === "dark" ? "Usar tema claro" : "Usar tema escuro"}
          >
            {tema === "dark" ? "☾" : "☀"}
          </button>
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
    </div>
  );
}
