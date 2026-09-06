import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// noVNC uses top-level await, which Vite's default target rejects. This is the oldest
// baseline that supports it; the interface is an administration screen for one person, not a
// public page that has to reach an ancient browser.
//
// It has to be set in two places: `build.target` covers the production bundle, and
// `optimizeDeps` covers the dependency pre-bundle the dev server builds — miss the second and
// the app builds but will not start in development.
const BROWSER_TARGET = ["es2022", "chrome89", "edge89", "firefox89", "safari15"];

// The dev server proxies the API and the VNC websocket to the backend, so the app runs on
// one origin in development exactly as it does in production, where FastAPI serves the
// built files itself. Without the websocket entry the login stream would fail only in
// development, which is the worst place for a difference to hide.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        // The backend is another container when the dev stack runs under compose, so its
        // address is supplied rather than assumed; 127.0.0.1 is right only when both halves
        // run on the same machine.
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: BROWSER_TARGET,
  },
  optimizeDeps: {
    esbuildOptions: { target: "es2022" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      reportsDirectory: "coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/main.tsx",
        "src/test/**",
        "src/**/*.test.{ts,tsx}",
        // Types only; there is nothing to execute.
        "src/api/types.ts",
        "src/types/**",
      ],
    },
  },
});
