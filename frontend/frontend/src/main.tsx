import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '@/store/AuthProvider'
import { HubProvider } from '@/store/HubProvider'
import { App } from './App'
import './index.css'

/* AuthProvider wraps HubProvider, not the other way round: the hub's chrome
   reads the signed-in user, and nothing in auth needs the hub. */
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <HubProvider>
          <App />
        </HubProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
