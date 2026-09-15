import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // Dev-time proxy so the app can call same-origin /api/* and never think
      // about CORS locally. VITE_API_BASE (see .env.example) points this at the
      // FastAPI backend; in a production build there is no proxy, so set
      // VITE_API_BASE to the deployed backend's absolute URL instead.
      proxy: {
        '/api': {
          target: env.VITE_API_BASE || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
