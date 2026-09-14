import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

// Both the dev server and `vite preview` proxy /api to the backend, so the
// browser sees a single origin and CORS never enters the picture locally.
// Sharing one definition keeps a production build testable under the same
// conditions it was developed under.
const apiProxy: Record<string, ProxyOptions> = {
  '/api': {
    target: API_TARGET,
    changeOrigin: true,
    // Answers arrive as a stream; a proxy that buffers would hold the whole
    // reply until the last token and defeat the point.
    configure: (proxy) => {
      proxy.on('proxyRes', (proxyRes) => {
        proxyRes.headers['cache-control'] = 'no-cache, no-transform'
      })
    },
  },
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors the `@/*` paths mapping in tsconfig.json — both need it: one
    // for type-checking, one for bundling.
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 5173 unless the environment names another, so a second instance can be
    // run alongside a first without editing this file.
    port: Number(process.env.PORT) || 5173,
    proxy: apiProxy,
  },
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
