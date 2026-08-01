import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { devMockServer } from './dev-mock-server.js'

// The Pico serves the built app as static files, so:
//  - base './' makes asset URLs relative
//  - build output goes to the repo-root www/ folder (uploaded to the Pico)
export default defineConfig({
  plugins: [react(), tailwindcss(), devMockServer()],
  base: './',
  build: {
    outDir: '../www',
    emptyOutDir: true,
  },
  server: {
    host: true,
  },
})
