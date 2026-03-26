import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1", "api.fotonai.online"],
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      all: true,
      include: ["src/**/*.{js,jsx}"],
      exclude: ["src/main.jsx"],
      thresholds: {
        lines: 80,
        functions: 80,
        statements: 80,
        branches: 70,
      },
    },
  },
});
