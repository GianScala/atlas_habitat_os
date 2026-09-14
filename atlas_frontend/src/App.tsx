/**
 * Routing.
 *
 * Four routes and no state of its own — the pages own theirs.
 *
 *   /                    a new conversation
 *   /c/:conversationId   a stored one
 *   /dashboard           the charts
 *   /settings/:tab       AI & models, or database nomenclature
 *
 * The dashboard is loaded on demand. Its charting library is most of the
 * bundle, and someone who only ever asks questions should not pay for it. The
 * settings page is loaded the same way for a different reason: it is visited
 * once, when something needs setting up, and rarely again.
 *
 * `/models` and `/naming` were earlier addresses for halves of the settings
 * page, kept as redirects so old bookmarks still land.
 */

import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import ChatPage from '@/pages/ChatPage'

const DashboardPage = lazy(() => import('@/pages/dashboard/DashboardPage'))
const SettingsPage = lazy(() => import('@/pages/settings/SettingsPage'))

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/c/:conversationId" element={<ChatPage />} />
        <Route
          path="/dashboard"
          element={
            <Suspense fallback={<p className="dashboard__status">Loading dashboard…</p>}>
              <DashboardPage />
            </Suspense>
          }
        />
        <Route
          path="/settings/:tab"
          element={
            <Suspense fallback={<p className="dashboard__status">Loading settings…</p>}>
              <SettingsPage />
            </Suspense>
          }
        />
        <Route path="/settings" element={<Navigate to="/settings/ai_models" replace />} />
        {/* Both were addresses this content used to live at. */}
        <Route
          path="/naming"
          element={<Navigate to="/settings/database_nomenclature" replace />}
        />
        <Route path="/models" element={<Navigate to="/settings/ai_models" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
