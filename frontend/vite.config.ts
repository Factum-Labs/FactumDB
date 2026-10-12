import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { pdfAssets } from './pdfAssets.js'

// Tauri expects a fixed port and does not tolerate the dev server moving.
export default defineConfig({
  plugins: [react(), pdfAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: { ignored: ['**/src-tauri/**'] },
  },
})
