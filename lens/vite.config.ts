/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the pairing relay runs separately (`python -m lattice.lens.relay`); Vite
// forwards the WebSocket to it. In production the relay serves this app itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    host: true, // reachable from a second device on the same network
    proxy: { '/ws': { target: 'ws://localhost:8090', ws: true } },
  },
  test: { environment: 'jsdom', setupFiles: ['./src/__tests__/setup.ts'], css: false },
})
