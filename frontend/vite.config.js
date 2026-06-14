import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
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
