import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const rootDir = import.meta.dirname

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "./src"),
    },
  },
  base: "/static/",
  build: {
    outDir: path.resolve(rootDir, "../web/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    minify: true,
    reportCompressedSize: false,
  },
})
