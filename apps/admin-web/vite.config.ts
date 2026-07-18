import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const appDirectory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  envDir: path.resolve(appDirectory, "../.."),
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 4174,
    proxy: {
      "/api/admin": "http://localhost:8000",
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4174,
  },
});
