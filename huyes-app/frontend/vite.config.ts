import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Huyes Coffee',
        short_name: 'Huyes',
        description: '咖啡豆品質分析報告',
        theme_color: '#1a0a00',
        background_color: '#1a0a00',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/batch': 'http://localhost:8765',
      '/batches': 'http://localhost:8765',
      '/origins': 'http://localhost:8765',
    },
  },
})
