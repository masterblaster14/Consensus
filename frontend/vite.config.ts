import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev we proxy /api and /ws to the FastAPI backend so the app can use
// relative URLs everywhere and never needs CORS. For a deployed build set
// VITE_API_URL instead (see .env.example).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
