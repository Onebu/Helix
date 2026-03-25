import './i18n'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { client } from './client/client.gen'
import { getApiBaseUrl } from './lib/api-config'

// Configure @hey-api client with dynamic base URL from VITE_API_URL
client.setConfig({ baseUrl: getApiBaseUrl() })

// Theme is initialized in index.html <script> to prevent FOUC.
// It reads localStorage('helix-theme') or falls back to system preference.

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
