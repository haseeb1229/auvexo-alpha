import { defineConfig } from "vitest/config";
export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    cors: { origin: "http://127.0.0.1:5173" },
  },
  preview: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { url: "http://127.0.0.1:8765" } },
    globals: true,
    setupFiles: ["./tests/setup.ts"],
  },
});
