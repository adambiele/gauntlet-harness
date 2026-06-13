import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    // Allow VITE_API_URL to be injected at build time
    __VITE_API_URL__: JSON.stringify(process.env.VITE_API_URL || ''),
  },
})
