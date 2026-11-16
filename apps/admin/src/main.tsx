import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'

import { createQueryClient } from './lib/queryClient'
import { Providers } from './providers'
import { routes } from './routes'
import './styles.css'

const router = createBrowserRouter(routes, { basename: import.meta.env.BASE_URL.replace(/\/$/, '') })
const client = createQueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
)
