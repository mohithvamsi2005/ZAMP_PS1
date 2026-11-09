import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backend = process.env.ZAMP_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      // Health endpoint lives outside /api (Phase 1 contract) — same-origin proxy needed too
      '/health': {
        target: backend,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/health': {
        target: backend,
        changeOrigin: true,
      },
    },
  },
})
