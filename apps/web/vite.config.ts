import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

const appDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(appDir, "../..");

export default defineConfig({
  // Force Vite to load environment variables from the monorepo root
  envDir: repoRoot,
  plugins: [
    react(),
    VitePWA({
      // injectManifest, not generateSW: the app needs its own push and
      // notificationclick handlers, which a generated worker does not have.
      strategies: "injectManifest",
      srcDir: "src/pwa",
      filename: "sw.ts",
      registerType: "prompt",
      injectRegister: false,
      includeAssets: ["icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "Nerkhbaan",
        short_name: "Nerkhbaan",
        description: "Live gold, silver, currency and crypto prices.",
        theme_color: "#051024",
        background_color: "#020817",
        display: "standalone",
        orientation: "portrait-primary",
        scope: "/",
        start_url: "/",
        icons: [
          {
            src: "/icons/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any maskable"
          },
          {
            src: "/icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any maskable"
          }
        ]
      },
      injectManifest: {
        // Precache only what the app actually loads. The previous glob pulled
        // in every weight of every bundled font family plus large images, so a
        // first visit downloaded megabytes before the dashboard was usable.
        globPatterns: ["**/*.{js,css,html,ico}"],
        globIgnores: ["**/fonts/**", "**/node_modules/**"],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024
      },
      devOptions: {
        // A worker running in dev serves stale bundles and hides real changes.
        enabled: false
      }
    })
  ],
  resolve: {
    alias: {
      "@": path.resolve(appDir, "src"),
      "@nerkhbaan/ui": path.resolve(repoRoot, "packages/ui/src")
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router", "react-router-dom"],
          charts: ["lightweight-charts"],
          query: ["@tanstack/react-query"],
          motion: ["motion"],
          ui: ["@radix-ui/react-dialog", "@radix-ui/react-dropdown-menu", "@radix-ui/react-popover"],
          http: ["axios"]
        }
      }
    }
  }
});
