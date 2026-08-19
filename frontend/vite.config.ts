import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: './', // relative — serve từ bất kỳ path nào (FastAPI mount /)
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // dev: frontend (5173) → backend FastAPI
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
