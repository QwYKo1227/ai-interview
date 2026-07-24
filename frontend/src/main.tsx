import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import router from './router'
import './index.css'
import { AuthProvider } from './contexts/AuthContext'
import { PlatformAuthProvider } from './contexts/PlatformAuthContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <PlatformAuthProvider>
        <RouterProvider router={router} />
      </PlatformAuthProvider>
    </AuthProvider>
  </StrictMode>,
)
