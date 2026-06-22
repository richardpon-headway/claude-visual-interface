import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The daemon (FastAPI) listens here; dev-server requests for the live stream
// and health check are proxied to it so the SPA can use same-origin paths.
const DAEMON = "http://127.0.0.1:47825";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5175,
    strictPort: true,
    proxy: {
      "/ws": { target: DAEMON, changeOrigin: false, ws: true },
      "/health": { target: DAEMON, changeOrigin: false },
      "/sessions": {
        target: DAEMON,
        changeOrigin: false,
        // The SPA also has a "/sessions" page route. A browser navigation
        // (Accept: text/html) should fall through to index.html so the React
        // app boots; only data fetches (Accept: */*) get proxied to the daemon.
        bypass(req) {
          if (req.headers.accept?.includes("text/html")) return "/index.html";
        },
      },
      "/chats": { target: DAEMON, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
    css: false,
  },
});
