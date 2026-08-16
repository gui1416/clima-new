import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import "./estilos/base.css";
import { iniciarTema } from "./tema";

// Antes de renderizar, para não haver piscada de tema errado.
iniciarTema();

const raiz = document.getElementById("raiz");
if (!raiz) throw new Error("elemento #raiz não encontrado");

createRoot(raiz).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
