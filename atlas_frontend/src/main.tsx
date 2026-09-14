import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './styles/index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('No #root element — index.html is not the page that loaded.')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
