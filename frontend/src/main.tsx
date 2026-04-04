import './i18n'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { client } from './client/client.gen'
import { getApiBaseUrl } from './lib/api-config'
import { getToken, clearToken } from './lib/auth'

// Configure @hey-api client with dynamic base URL from VITE_API_URL
client.setConfig({ baseUrl: getApiBaseUrl() })

// Add JWT auth header to all API requests
client.interceptors.request.use((request) => {
  const token = getToken()
  if (token) {
    request.headers.set('Authorization', `Bearer ${token}`)
  }
  return request
})

// Handle 401 globally — clear token and redirect to login
client.interceptors.response.use((response) => {
  if (response.status === 401) {
    clearToken()
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
  }
  return response
})

// Theme is initialized in index.html <script> to prevent FOUC.
// It reads localStorage('helix-theme') or falls back to system preference.

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
