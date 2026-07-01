import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    // Installable + offline app shell. Generated notes/cards already live in
    // localStorage, so once the shell is precached they render with no network.
    // API calls aren't cached (generation needs the network anyway).
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'SmartStudy — ብልሃት ትምህርቲ',
        short_name: 'SmartStudy',
        description: 'AI study companion for the Ethiopian curriculum and EUEE prep.',
        theme_color: '#1E1610',
        background_color: '#1E1610',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' },
        ],
      },
      workbox: {
        // Precache the built shell; fall back to index.html for SPA routes offline.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api/, /^\/static/],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // Past-exam question images are served by the backend at /static/exam-images.
      '/static': { target: 'http://localhost:8000', changeOrigin: true },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          // Disable socket idle timeout on the proxy→backend leg so long-running
          // WebSocket connections (LLM generation can take 60-120 s) don't get
          // silently dropped when no messages are flowing.
          proxy.on('open', (proxySocket) => {
            proxySocket.setTimeout(0)
          })
        },
      },
    },
  },
})
