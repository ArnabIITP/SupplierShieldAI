import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Keep browser requests same-origin during local development. This avoids
// CORS/preflight failures when the frontend is opened as 127.0.0.1 instead of
// localhost (or vice versa). Production deployments should set VITE_API_URL.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
