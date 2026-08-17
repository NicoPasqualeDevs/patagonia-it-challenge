import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/runs": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/agents": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/tools": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/examples": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8080", ws: true },
    },
  },
});
