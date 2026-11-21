import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relative base: the build is copied to the repo root and served by GitHub Pages
// at https://shema.agmonp.com/ (and also works from any sub-folder).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          r3f: ['@react-three/fiber', '@react-three/drei'],
          motion: ['gsap', 'lenis'],
        },
      },
    },
  },
})
