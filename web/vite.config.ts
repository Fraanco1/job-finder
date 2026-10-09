import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the build works from GitHub Pages sub-paths and the local server alike.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    // `python -m jobfinder serve` exposes /api/*; proxy it during `npm run dev`.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
