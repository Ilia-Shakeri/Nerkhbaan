import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

const appDirectory = path.dirname(fileURLToPath(import.meta.url));
const environmentDirectory = path.resolve(appDirectory, "../..");

export default defineConfig(({ mode }) => {
  const localPreview = process.env.NERKHBAAN_LOCAL_PREVIEW === '1';
  const environment = localPreview ? process.env : loadEnv(mode, environmentDirectory, "VITE_");
  const configuredBase = environment.VITE_ADMIN_BASE_PATH?.trim() || "/";
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]*$/.test(configuredBase)) {
    throw new Error("VITE_ADMIN_BASE_PATH must be an absolute local path such as / or /admin/");
  }
  const base = configuredBase.endsWith("/") ? configuredBase : `${configuredBase}/`;

  return {
    base,
    envDir: localPreview ? false : environmentDirectory,
    cacheDir: localPreview ? path.join(environmentDirectory, 'node_modules/.vite/nerkhbaan-local-admin') : undefined,
    plugins: [react()],
    server: {
      fs: { strict: true, deny: ['**/.env', '**/.env.*', '**/*.{crt,pem,key}', '**/.git/**',
        '**/.local-keys/**', '**/.local-preview/**', '**/*.private.*'] },
      host: "0.0.0.0",
      port: 4174,
      proxy: localPreview ? undefined : {
        "/api/admin": "http://localhost:8000",
      },
    },
    preview: {
      host: "0.0.0.0",
      port: 4174,
    },
  };
});
