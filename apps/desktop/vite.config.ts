import { defineConfig } from 'vite'
import path from 'path'
import { fileURLToPath } from 'url'
import react from '@vitejs/plugin-react'

const appDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(appDir, '../..')

// Custom plugin to resolve Figma-specific assets
function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id: string) {
      if (id.startsWith('figma:asset/')) {
        const assetPath = id.replace('figma:asset/', '')
        return path.resolve(appDir, 'src/assets', assetPath)
      }
    }
  }
}

export default defineConfig({
  // Force Vite to load environment variables from the monorepo root
  envDir: repoRoot,
  // Force relative paths to ensure successful asset loading in Electron's file:// protocol
  base: './', 
  plugins: [
    figmaAssetResolver(),
    react()
  ],
  resolve: {
    alias: {
      '@': path.resolve(appDir, 'src'),
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
  assetsInclude: ['**/*.svg', '**/*.csv'],
  server: {
    port: 5173,
    strictPort: true,
    host: true
  }
})
