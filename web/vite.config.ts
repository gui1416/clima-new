import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // A API operacional da Fase 0. A API de produto entra na Fase 3.
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
