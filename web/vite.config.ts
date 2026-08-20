import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Back-end em docker compose. Proxy em vez de CORS: em produção os dois
      // ficam atrás do mesmo host, e o desenvolvimento imita isso.
      // Prefixo /api porque as rotas do SPA (/eventos, /fontes) casariam com o
      // proxy antes do fallback e o navegador receberia JSON em vez da aplicação.
      // `ws: true` porque /api/eventos/stream é WebSocket: sem isso o proxy
      // responde 426 ao upgrade e o fluxo ao vivo nunca conecta em dev.
      "/api": { target: "http://localhost:8000", ws: true },
      "/saude": "http://localhost:8000",
    },
  },
  build: {
    // O chunk do MapLibre é ~803 KB e isso é irredutível — é o tamanho da
    // biblioteca. Como o limite vale por chunk, elevá-lo silencia só esse caso e
    // continua acusando se o código da aplicação (hoje ~12 KB) inchar.
    chunkSizeWarningLimit: 850,
    rollupOptions: {
      output: {
        // O MapLibre é ~800 KB minificado e praticamente nunca muda; o código da
        // aplicação muda a cada deploy. Em chunks separados, atualizar a
        // aplicação não invalida o cache do mapa no navegador do usuário.
        manualChunks: {
          maplibre: ["maplibre-gl"],
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
});
