/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    // Component/interaction tests (Vitest + Testing Library, jsdom).
    // E2E smoke flows live in ./e2e and run with Playwright, not here.
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    css: false,
    testTimeout: 20_000,   // jsdom + user-event on slow/AV-scanned machines
    hookTimeout: 20_000,
    coverage: { provider: "v8", reporter: ["text", "html"], include: ["src/**"] },
  },
});
