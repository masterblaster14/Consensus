import { Route, Routes } from 'react-router-dom'
import LandingApp from './landing/LandingApp'
import DashboardApp from './dashboard/DashboardApp'
import { RequireAuth, SessionProvider } from './lib/session'
import { ThemeProvider } from './lib/theme'

/**
 * The whole router: `/app/*` is the signed-in dashboard, everything else is
 * the public site (marketing, sign in / sign up, onboarding).
 *
 * Both providers sit above the split so theme and session are shared: the
 * theme toggle works on every page, and the dashboard can be gated behind
 * `RequireAuth`.
 */
export default function App() {
  return (
    <ThemeProvider>
      <SessionProvider>
        <Routes>
          <Route
            path="/app/*"
            element={
              <RequireAuth>
                <DashboardApp />
              </RequireAuth>
            }
          />
          <Route path="/*" element={<LandingApp />} />
        </Routes>
      </SessionProvider>
    </ThemeProvider>
  )
}
