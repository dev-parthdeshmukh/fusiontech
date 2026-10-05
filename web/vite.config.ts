import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` proxies /api to the FastAPI backend on :8000.
// Build: output goes straight into the Python package so `fusionmap serve` hosts it.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "../fusionmap/static", emptyOutDir: true, chunkSizeWarningLimit: 900 },
});
