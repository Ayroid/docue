import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

const API_PROXY = {
  '/api': { target: 'http://localhost:8000', changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  /* The app talks to the backend over a relative `/api` path so it stays
     same-origin and never hits CORS. `vite preview` does not inherit
     `server.proxy`, so the production-build server needs its own copy. */
  server: {
    port: 5173,
    proxy: API_PROXY,
  },
  preview: {
    proxy: API_PROXY,
  },
})
