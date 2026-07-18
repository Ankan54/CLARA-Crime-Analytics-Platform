import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The hosted backend's Catalyst AppSail gateway auto-answers CORS preflight
// (OPTIONS) requests at the platform level with a bare 200 and no CORS
// headers -- it never reaches our FastAPI app/CORSMiddleware at all. Any
// browser POST/PUT with a JSON body or custom header (i.e. most write calls)
// triggers a preflight and gets blocked with "Failed to fetch". Proxying
// through Vite's dev server sidesteps this for local dev: the browser only
// ever talks same-origin to localhost:5173, and Vite's Node process (not
// subject to browser CORS) makes the actual cross-origin call.
const HOSTED_BACKEND = 'https://ksp-catalyst-backend-50043496759.development.catalystappsail.in'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: HOSTED_BACKEND, changeOrigin: true },
      '/ws': { target: HOSTED_BACKEND, changeOrigin: true, ws: true },
    },
  },
})
