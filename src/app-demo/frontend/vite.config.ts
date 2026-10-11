import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { strictPort: true, proxy: { "/api": "http://127.0.0.1:8017" } },
  build: { outDir: "../dist", emptyOutDir: true },
});
