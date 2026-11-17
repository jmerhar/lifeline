import { defineConfig, mergeConfig } from "vite";
import react from "@vitejs/plugin-react";
import { app } from "@jmerhar/frontend-config/vite";
import { test } from "@jmerhar/frontend-config/vitest";

// The shared settings supply the build's browser targets, all of which run noVNC's top-level
// await. The dependency pre-bundle the dev server builds needs the same capability named
// separately, or the app builds but will not start in development.
//
// The dev server proxies the API and the VNC websocket to the backend, so the app runs on one
// origin in development exactly as it does in production, where FastAPI serves the built files
// itself. Without the websocket the login stream would fail only in development, which is the
// worst place for a difference to hide. The backend is another container when the dev stack runs
// under compose, so its address comes from VITE_API_TARGET, as the shared settings read it.
const API_TARGET = process.env.VITE_API_TARGET || "http://127.0.0.1:8000";

export default mergeConfig(
  app(),
  defineConfig({
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true, ws: true },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
    optimizeDeps: {
      esbuildOptions: { target: "es2022" },
    },
    test: {
      ...test({
        setupFiles: ["./src/test/setup.ts"],
        coverage: {
          include: ["src/**/*.{ts,tsx}"],
          exclude: [
            "src/main.tsx",
            "src/test/**",
            // Types only; there is nothing to execute.
            "src/api/types.ts",
            "src/types/**",
          ],
        },
      }),
      globals: true,
      css: true,
    },
  }),
);
