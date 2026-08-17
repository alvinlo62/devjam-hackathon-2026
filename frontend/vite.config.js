import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 走 proxy 就不用處理 CORS，前端一律打 /api
    proxy: { '/api': 'http://localhost:8000' },
  },
})
