import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useState } from "react";

import {
  ROTAS,
  TelaAlertas,
  TelaEventos,
  TelaFontes,
  TelaMapa,
  TelaProcedencia,
  TelaRelatorios,
} from "./rotas";
import { alternarTema, temaAtual } from "./tema";

const GRUPOS = [
  { id: "monitoramento", rotulo: "MONITORAMENTO" },
  { id: "distribuicao", rotulo: "DISTRIBUIÇÃO" },
] as const;

export function App() {
  const [tema, setTema] = useState(temaAtual);
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

          {/* Enquanto não há ingestão em tempo real na interface, o rótulo diz
              "demonstração" em vez de "ao vivo". */}
          <span className="pilula">
            <i className="ponto high" />
            dados de demonstração
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
            <Route path="/" element={<Navigate to="/mapa" replace />} />
            <Route path="/mapa" element={<TelaMapa />} />
            <Route path="/eventos" element={<TelaEventos />} />
            <Route path="/procedencia" element={<TelaProcedencia />} />
            <Route path="/fontes" element={<TelaFontes />} />
            <Route path="/alertas" element={<TelaAlertas />} />
            <Route path="/relatorios" element={<TelaRelatorios />} />
            <Route path="*" element={<Navigate to="/mapa" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
