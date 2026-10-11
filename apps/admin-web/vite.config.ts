import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const appDirectory = path.dirname(fileURLToPath(import.meta.url));
const environmentDirectory = path.resolve(appDirectory, "../..");

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, environmentDirectory, "VITE_");
  const configuredBase = environment.VITE_ADMIN_BASE_PATH?.trim() || "/";
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]*$/.test(configuredBase)) {
    throw new Error("VITE_ADMIN_BASE_PATH must be an absolute local path such as / or /admin/");
  }
  const base = configuredBase.endsWith("/") ? configuredBase : `${configuredBase}/`;

  return {
    base,
    envDir: environmentDirectory,
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
  };
});
