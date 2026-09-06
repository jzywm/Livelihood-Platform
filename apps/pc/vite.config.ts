import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Electron 套壳下资源用相对路径加载
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
  },
})
