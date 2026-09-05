import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000. In dev, /api and /ws are proxied there so the
// app can use relative URLs and no CORS setup is needed. In production set
// VITE_API_URL (see .env.example) or serve the built files from the backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
