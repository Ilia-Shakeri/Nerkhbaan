import { defineConfig } from 'vite'
import path from 'path'
import react from '@vitejs/plugin-react'

// Custom plugin to resolve Figma-specific assets
function figmaAssetResolver() {
  return {
    name: 'figma-asset-resolver',
    resolveId(id: string) {
      if (id.startsWith('figma:asset/')) {
        const assetPath = id.replace('figma:asset/', '')
        return path.resolve(__dirname, 'src/assets', assetPath)
      }
    }
  }
}

export default defineConfig({
  // Force Vite to load environment variables from the monorepo root
  envDir: '../../',
  // Force relative paths to ensure successful asset loading in Electron's file:// protocol
  base: './', 
  plugins: [
    figmaAssetResolver(),
    react()
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@nerkhbaan/ui': path.resolve(__dirname, '../../packages/ui/src')
    }
  },
  assetsInclude: ['**/*.svg', '**/*.csv'],
  server: {
    port: 5173,
    strictPort: true,
    host: true
  }
})