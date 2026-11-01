import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8080", rewrite: (path) => path.replace(/^\/api/, "") },
      "/agent": { target: "http://localhost:8090", rewrite: (path) => path.replace(/^\/agent/, "") },
    },
  },
});
