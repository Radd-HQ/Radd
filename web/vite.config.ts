import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** Dev-only settings; production serves the built assets behind the same origin as the API. */
const DEV_SERVER_PORT = 5173;
const DEV_API_TARGET = "http://localhost:8000";
const API_PROXY_PREFIX = "/api";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: DEV_SERVER_PORT,
    proxy: {
      [API_PROXY_PREFIX]: {
        target: DEV_API_TARGET,
        changeOrigin: true,
        // Realtime WebSocket (spec 27) rides the same /api prefix.
        ws: true,
      },
      // Federated plugin bundles (spec 94) are served by the API at /plugins/<name>/… — without
      // this proxy the dev server 404s them and NO plugin UI (contribution toggles, plugin nav,
      // widgets) loads. The /shared shims live in web/public and are served by Vite directly.
      "/plugins": {
        target: DEV_API_TARGET,
        changeOrigin: true,
      },
    },
  },
});
