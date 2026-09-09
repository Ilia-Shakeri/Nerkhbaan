import { defineConfig } from 'vite'
import path from 'path'
import { fileURLToPath } from 'url'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

const appDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(appDir, '../..')

export default defineConfig({
  // Force Vite to load environment variables from the monorepo root
  envDir: repoRoot,
  // Force relative paths to ensure successful asset loading in Electron's file:// protocol
  base: './', 
  plugins: [
    react(),
    VitePWA({ disable: true })
  ],
  resolve: {
    alias: {
      '@': path.resolve(repoRoot, 'apps/web/src'),
      '@nerkhbaan/ui': path.resolve(repoRoot, 'packages/ui/src')
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router', 'react-router-dom'],
          charts: ['recharts'],
          motion: ['motion'],
          ui: ['@radix-ui/react-dialog', '@radix-ui/react-dropdown-menu', '@radix-ui/react-popover'],
          http: ['axios']
        }
      }
    }
  },
  publicDir: path.resolve(repoRoot, 'apps/web/public'),
  assetsInclude: ['**/*.svg', '**/*.csv'],
  server: {
    port: 5173,
    strictPort: true,
    host: true
  }
})
