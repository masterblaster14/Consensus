import { useEffect } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import LandingApp from './landing/LandingApp'
import DashboardApp from './dashboard/DashboardApp'

// Two surfaces, one router:
//   /            marketing site, sign-in / onboarding, admin console, "My Teams"  (src/landing)
//   /app/*       the per-team agent dashboard                                       (src/dashboard)
// LandingApp owns everything outside /app and keeps its own view state internally.
export default function App() {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <Routes>
        <Route path="/app/*" element={<DashboardApp />} />
        <Route path="/*" element={<LandingApp />} />
      </Routes>
    </BrowserRouter>
  )
}

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }) }, [pathname])
  return null
}
