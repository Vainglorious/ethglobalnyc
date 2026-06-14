import { defineConfig } from 'vite'

// WorldColony is a self-contained static Three.js app (index.html + public/dinasty
// classic scripts + vendored three in public/vendor). No bundler plugins needed.
export default defineConfig({
  server: {
    port: 5173,
    host: true,
  },
})
