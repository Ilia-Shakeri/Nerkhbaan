import { defineConfig } from 'vite'
import path from 'path'
import react from '@vitejs/plugin-react'

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
  plugins: [
    figmaAssetResolver(),
    react()
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  assetsInclude: ['**/*.svg', '**/*.csv'],
  server: {
    port: 5173,
    strictPort: true,
    host: true
  }
})
