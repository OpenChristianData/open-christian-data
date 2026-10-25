import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, rollupOptions: { input: resolve(import.meta.dirname, "review.html") } },
  server: { host: "127.0.0.1", port: 5174, proxy: { "/api/review/v1": "http://127.0.0.1:8766" } },
  test: { environment: "jsdom", setupFiles: "./src/review/test-setup.ts", css: true, include: ["src/review/**/*.test.tsx"], exclude: ["e2e/**", "node_modules/**", "dist/**"] },
});
