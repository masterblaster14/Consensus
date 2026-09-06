import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  projectApi,
  type Agent,
  type ApiKey,
  type ApiKeyCreated,
  type Claim,
  type Clash,
  type Counters,
  type GithubRepo,
  type Invite,
  type MemoryEntry,
  type MemoryType,
  type Project,
  type Resolution,
  type Task,
  type TaskStatus,
  type VerdictLog,
  type WebhookStatus,
} from '../lib/api'
import { Icon } from '../lib/icons'
import { ProjectProvider, isOpen, severityOf, useProject, type ActivityItem, type ActivityKind, type UiAgentStatus, type UiSeverity } from '../lib/project'
import { RequireAdmin, describeError, firstName, initials, useSession, type Person, type Role } from '../lib/session'
import { ThemeToggle } from '../lib/theme'
import './dashboard.css'

/* ===================================================================
   The signed-in dashboard. Every number, row and card comes from the
   backend for the selected team, and the WebSocket keeps it current.
   =================================================================== */

/* -------------------------------------------------------------------
   Formatting
   ------------------------------------------------------------------- */

function relative(iso: string | null | undefined) {
  if (!iso) return '—'
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days}d ago`
}

function dayLabel(iso: string) {
  const date = new Date(iso)
  const now = Date.now()
  if (date.toDateString() === new Date(now).toDateString()) return 'Today'
  if (date.toDateString() === new Date(now - 86_400_000).toDateString()) return 'Yesterday'
  return date.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })
}

function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

const STATUS_LABEL: Record<UiAgentStatus, string> = { working: 'Working', reviewing: 'Reviewing', blocked: 'Blocked', idle: 'Idle' }
const MEMORY_LABEL: Record<MemoryType, string> = { ruling: 'Ruling', decision: 'Decision', discovery: 'Discovery', dead_end: 'Dead end', handoff: 'Handoff' }
const CLAIM_LABEL: Record<Claim['status'], string> = { open: 'Open', in_review: 'In review', retired: 'Retired' }
const AXES: { key: keyof Pick<Claim['stance'], 'error_handling' | 'auth_check' | 'data_access' | 'api_shape'>; label: string }[] = [
  { key: 'error_handling', label: 'Error handling' },
  { key: 'auth_check', label: 'Authentication' },
  { key: 'data_access', label: 'Data access' },
  { key: 'api_shape', label: 'API shape' },
]

/* -------------------------------------------------------------------
   Shared bits
   ------------------------------------------------------------------- */

function StatusBadge({ status }: { status: UiAgentStatus }) {
  return (
    <span className={`badge badge--${status}`}>
      <span className="badge__dot" />
      {STATUS_LABEL[status]}
    </span>
  )
}

function SeverityBadge({ severity }: { severity: UiSeverity }) {
  const tone = severity === 'HIGH' ? 'high' : severity === 'MEDIUM' ? 'medium' : 'low'
  return <span className={`badge badge--${tone}`}>{severity}</span>
}

function ClaimStatusBadge({ status }: { status: Claim['status'] }) {
  const tone = status === 'open' ? 'working' : status === 'in_review' ? 'reviewing' : 'idle'
  return <span className={`badge badge--${tone}`}>{CLAIM_LABEL[status]}</span>
}

function ConceptChips({ concepts }: { concepts: string[] }) {
  if (concepts.length === 0) return null
  return (
    <div className="chip-row">
      {concepts.map((concept) => (
        <span className="chip" key={concept}>
          {concept}
        </span>
      ))}
    </div>
  )
}

function DashNotice({ tone, children }: { tone: 'info' | 'warn' | 'danger' | 'success'; children: React.ReactNode }) {
  const glyph = tone === 'success' ? <Icon.Check size={16} /> : tone === 'info' ? <Icon.Info size={16} /> : <Icon.Alert size={16} />
  return (
    <div className={`dash-notice dash-notice--${tone}`}>
      {glyph}
      <div>{children}</div>
    </div>
  )
}

function CopyRow({ label, value, hint, mono = true }: { label: string; value: string; hint?: string; mono?: boolean }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const timer = setTimeout(() => setDone(false), 1600)
    return () => clearTimeout(timer)
  }, [done])
  return (
    <div className="dash-field">
      <span className="dash-field__label">{label}</span>
      <div className="copy-row">
        <input className={`dash-input${mono ? ' mono' : ''}`} value={value} readOnly />
        <button
          type="button"
          className={`copy-btn${done ? ' is-done' : ''}`}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value)
              setDone(true)
            } catch {
              setDone(false)
            }
          }}
        >
          {done ? <Icon.Check size={15} /> : <Icon.Copy />}
          {done ? 'Copied' : 'Copy'}
        </button>
      </div>
      {hint && <p className="dash-field__hint">{hint}</p>}
    </div>
  )
}

function AdminPage({ title, blurb, back, children }: { title: string; blurb: string; back: string; children: React.ReactNode }) {
  return (
    <div className="page page--narrow">
      <Link to={back} className="crumb">
        <Icon.ArrowLeft />
        Back
      </Link>
      <div className="page__head">
        <div>
          <h1>{title}</h1>
          <p>{blurb}</p>
        </div>
      </div>
      <section className="panel">
        <div className="panel__body">{children}</div>
      </section>
    </div>
  )
}

function Busy({ label }: { label: string }) {
  return (
    <>
      <Icon.Spinner size={15} className="spin" />
      {label}
    </>
  )
}

function EmptyPanel({ icon, title, body, action }: { icon?: React.ReactNode; title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="panel">
      <div className="empty-state">
        {icon ?? <Icon.Inbox />}
        <b>{title}</b>
        <p>{body}</p>
        {action}
      </div>
    </div>
  )
}

/** Run an async action with busy + error state. */
function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (problem) {
      setError(describeError(problem))
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, setError, run }
}

/* -------------------------------------------------------------------
   Shell
   ------------------------------------------------------------------- */

export default function DashboardApp() {
  const { teams } = useSession()
  const [params, setParams] = useSearchParams()

  const requested = params.get('team')
  const selected = teams.find((team) => team.id === requested) ?? teams[0] ?? null

  // Keep ?team= honest so a refresh or a shared link lands in the same place.
  useEffect(() => {
    if (!selected || requested === selected.id) return
    const next = new URLSearchParams(params)
    next.set('team', selected.id)
    setParams(next, { replace: true })
  }, [selected, requested, params, setParams])

  if (!selected) return <NoTeamsShell />

  return (
    <ProjectProvider team={selected} key={selected.id}>
      <Shell />
    </ProjectProvider>
  )
}

/** An account with no team yet still gets the shell, chrome and a way out. */
function NoTeamsShell() {
  const { user, org, isAdmin, signOut } = useSession()
  const navigate = useNavigate()

  return (
    <div className="app-shell" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div className="main">
        <header className="topbar">
          <Link to="/" className="dash-ghost-button">
            <Icon.Logo size={18} />
            Consensus
          </Link>
          <div className="topbar__spacer" />
          <div className="topbar__actions">
            <ThemeToggle />
            <button
              type="button"
              className="dash-ghost-button"
              onClick={() => {
                signOut()
                navigate('/')
              }}
            >
              <Icon.LogOut />
              Sign out
            </button>
          </div>
        </header>

        <Routes>
          <Route
            path="teams/create"
            element={
              <RequireAdmin>
                <CreateTeamPage />
              </RequireAdmin>
            }
          />
          <Route
            path="*"
            element={
              <div className="page">
                <div className="placeholder">
                  <div>
                    <div className="placeholder__icon">
                      <Icon.Layers size={26} />
                    </div>
                    <h2>{org?.name ?? 'Your organisation'} has no teams yet</h2>
                    <p>
                      {isAdmin
                        ? 'Create one. A team maps to one repository and one shared memory, and every member of the organisation can see it.'
                        : 'An admin needs to create the first team. You will see it here the moment they do.'}
                    </p>
                    <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
                      {isAdmin && (
                        <Link to="/app/teams/create" className="dash-primary-button">
                          <Icon.Plus />
                          Create a team
                        </Link>
                      )}
                      <Link to="/" className="dash-ghost-button">
                        Back to site
                      </Link>
                    </div>
                    <p style={{ marginTop: 22, fontSize: '0.75rem' }}>Signed in as {user?.email}</p>
                  </div>
                </div>
              </div>
            }
          />
        </Routes>
      </div>
    </div>
  )
}

function Shell() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { live, loading, error, refresh } = useProject()

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <div className="main">
        <TopBar onOpenSidebar={() => setSidebarOpen(true)} />

        {error && (
          <div style={{ padding: '14px 26px 0' }}>
            <DashNotice tone="danger">
              {error}{' '}
              <button type="button" className="link" onClick={() => void refresh()}>
                Retry
              </button>
            </DashNotice>
          </div>
        )}

        <Routes>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<OverviewPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:agentId" element={<AgentDetailPage />} />
          <Route path="conflicts" element={<ConflictsPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="claims" element={<ClaimsPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="integrations" element={<IntegrationsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="teams" element={<TeamsPage />} />
          <Route path="teams/create" element={<RequireAdmin><CreateTeamPage /></RequireAdmin>} />
          <Route path="teams/delete" element={<RequireAdmin><DeleteTeamPage /></RequireAdmin>} />
          <Route path="teams/domain" element={<RequireAdmin><DomainPage /></RequireAdmin>} />
          <Route path="members" element={<RequireAdmin><MembersPage /></RequireAdmin>} />
          <Route path="members/add" element={<RequireAdmin><AddMemberPage /></RequireAdmin>} />
          <Route path="members/remove" element={<RequireAdmin><RemoveMemberPage /></RequireAdmin>} />
          <Route path="members/restrict" element={<RequireAdmin><RestrictMemberPage /></RequireAdmin>} />
          <Route path="*" element={<Navigate to="dashboard" replace />} />
        </Routes>

        <footer>
          <span>Consensus · {new Date().getFullYear()}</span>
          <span className="live-status">
            <span className={`live-dot${live ? ' is-live' : ''}`} />
            {loading ? 'Loading…' : live ? 'Live' : 'Reconnecting…'}
          </span>
        </footer>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------
   Sidebar
   ------------------------------------------------------------------- */

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, org, orgs, isAdmin, teams, signOut, switchOrg } = useSession()
  const { team, agents, claims, clashes, memory, tasks } = useProject()
  const [, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()

  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [openGroup, setOpenGroup] = useState<'teams' | 'members' | null>(() =>
    location.pathname.startsWith('/app/members') ? 'members' : location.pathname.startsWith('/app/teams') ? 'teams' : null,
  )

  const openClaims = claims.filter((claim) => claim.status === 'open').length
  const openClashes = clashes.filter(isOpen).length
  const openTasks = tasks.filter((t) => t.status !== 'done').length
  const withTeam = (path: string) => `${path}?team=${team.id}`
  const isOn = (path: string) => location.pathname === path

  const mainNav = [
    { to: withTeam('/app/dashboard'), match: '/app/dashboard', label: 'Overview', icon: <Icon.Grid /> },
    { to: withTeam('/app/agents'), match: '/app/agents', label: 'Agents', icon: <Icon.Bot />, count: agents.length },
    { to: withTeam('/app/claims'), match: '/app/claims', label: 'Claims', icon: <Icon.Flag />, count: openClaims },
    { to: withTeam('/app/conflicts'), match: '/app/conflicts', label: 'Conflicts', icon: <Icon.Bolt />, count: openClashes, alert: openClashes > 0 },
  ]
  const knowledgeNav = [
    { to: withTeam('/app/memory'), match: '/app/memory', label: 'Shared memory', icon: <Icon.Brain />, count: memory.length },
    { to: withTeam('/app/activity'), match: '/app/activity', label: 'Activity', icon: <Icon.Pulse /> },
  ]

  return (
    <aside className={`sidebar${open ? ' is-open' : ''}`}>
      <div className="sidebar__brand">
        <Icon.Logo size={24} />
        Consensus
      </div>

      <div className="workspace">
        <button type="button" className="workspace__trigger" aria-expanded={switcherOpen} onClick={() => setSwitcherOpen((v) => !v)}>
          <span className="workspace__mark">{initials(team.name)}</span>
          <span className="workspace__name">
            <b>{team.name}</b>
            <span>{team.repo ?? 'No repository'}</span>
          </span>
          <span className="workspace__chev">
            <Icon.ChevronDown size={14} />
          </span>
        </button>

        {switcherOpen && (
          <div className="workspace__menu">
            <div className="workspace__empty">Teams in {org?.name}</div>
            {teams.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`workspace__option${item.id === team.id ? ' is-active' : ''}`}
                onClick={() => {
                  setSwitcherOpen(false)
                  onClose()
                  setParams({ team: item.id })
                }}
              >
                {item.id === team.id ? <Icon.Check size={14} /> : <span style={{ width: 14 }} />}
                {item.name}
              </button>
            ))}
            {isAdmin && (
              <button
                type="button"
                className="workspace__option"
                onClick={() => {
                  setSwitcherOpen(false)
                  onClose()
                  navigate('/app/teams/create')
                }}
              >
                <Icon.Plus size={14} />
                Create team
              </button>
            )}
            {orgs.length > 1 && (
              <>
                <div className="workspace__empty">Organisations</div>
                {orgs.map((o) => (
                  <button
                    type="button"
                    key={o.id}
                    className={`workspace__option${o.id === org?.id ? ' is-active' : ''}`}
                    onClick={() => {
                      setSwitcherOpen(false)
                      onClose()
                      switchOrg(o.id)
                      navigate('/app/dashboard')
                    }}
                  >
                    {o.id === org?.id ? <Icon.Check size={14} /> : <span style={{ width: 14 }} />}
                    {o.name}
                  </button>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      <nav className="nav">
        <div className="nav__label">Workspace</div>
        {mainNav.map((item) => (
          <NavLink key={item.match} to={item.to} onClick={onClose} className={() => `nav__item${isOn(item.match) ? ' is-active' : ''}`}>
            {item.icon}
            {item.label}
            {item.count !== undefined && item.count > 0 && <span className={`nav__count${item.alert ? ' nav__count--alert' : ''}`}>{item.count}</span>}
          </NavLink>
        ))}

        <div className="nav__label">Knowledge</div>
        {knowledgeNav.map((item) => (
          <NavLink key={item.match} to={item.to} onClick={onClose} className={() => `nav__item${isOn(item.match) ? ' is-active' : ''}`}>
            {item.icon}
            {item.label}
            {item.count !== undefined && item.count > 0 && <span className="nav__count">{item.count}</span>}
          </NavLink>
        ))}

        {isAdmin ? (
          <>
            <div className="nav__label">
              <Icon.Shield size={11} />
              Administration
            </div>
            <button type="button" className="nav__item" aria-expanded={openGroup === 'teams'} onClick={() => setOpenGroup(openGroup === 'teams' ? null : 'teams')}>
              <Icon.Layers />
              Manage teams
              <Icon.Chevron size={13} className={`nav__chev${openGroup === 'teams' ? ' is-open' : ''}`} />
            </button>
            {openGroup === 'teams' && (
              <div className="nav__sub">
                <NavLink to="/app/teams" onClick={onClose} className={() => `nav__item${isOn('/app/teams') ? ' is-active' : ''}`}>All teams</NavLink>
                <NavLink to="/app/teams/create" onClick={onClose} className={() => `nav__item${isOn('/app/teams/create') ? ' is-active' : ''}`}>Create team</NavLink>
                <NavLink to="/app/teams/delete" onClick={onClose} className={() => `nav__item${isOn('/app/teams/delete') ? ' is-active' : ''}`}>Archive team</NavLink>
                <NavLink to="/app/teams/domain" onClick={onClose} className={() => `nav__item${isOn('/app/teams/domain') ? ' is-active' : ''}`}>Auto-join domain</NavLink>
              </div>
            )}
            <button type="button" className="nav__item" aria-expanded={openGroup === 'members'} onClick={() => setOpenGroup(openGroup === 'members' ? null : 'members')}>
              <Icon.Users />
              Manage members
              <Icon.Chevron size={13} className={`nav__chev${openGroup === 'members' ? ' is-open' : ''}`} />
            </button>
            {openGroup === 'members' && (
              <div className="nav__sub">
                <NavLink to="/app/members" onClick={onClose} className={() => `nav__item${isOn('/app/members') ? ' is-active' : ''}`}>All members</NavLink>
                <NavLink to="/app/members/add" onClick={onClose} className={() => `nav__item${isOn('/app/members/add') ? ' is-active' : ''}`}>Invite member</NavLink>
                <NavLink to="/app/members/remove" onClick={onClose} className={() => `nav__item${isOn('/app/members/remove') ? ' is-active' : ''}`}>Remove member</NavLink>
                <NavLink to="/app/members/restrict" onClick={onClose} className={() => `nav__item${isOn('/app/members/restrict') ? ' is-active' : ''}`}>Restrict member</NavLink>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="nav__label">Your teams</div>
            <NavLink to="/app/teams" onClick={onClose} className={() => `nav__item${isOn('/app/teams') ? ' is-active' : ''}`}>
              <Icon.Layers />
              Teams
              <span className="nav__count">{teams.length}</span>
            </NavLink>
          </>
        )}

        <div className="nav__label">Manage</div>
        <NavLink to={withTeam('/app/tasks')} onClick={onClose} className={() => `nav__item${isOn('/app/tasks') ? ' is-active' : ''}`}>
          <Icon.Calendar />
          Tasks
          {openTasks > 0 && <span className="nav__count">{openTasks}</span>}
        </NavLink>
        <NavLink to={withTeam('/app/integrations')} onClick={onClose} className={() => `nav__item${isOn('/app/integrations') ? ' is-active' : ''}`}>
          <Icon.Plug />
          Integrations
        </NavLink>
        <NavLink to={withTeam('/app/settings')} onClick={onClose} className={() => `nav__item${isOn('/app/settings') ? ' is-active' : ''}`}>
          <Icon.Settings />
          Settings
        </NavLink>
      </nav>

      <div className="sidebar__foot">
        {userMenuOpen && (
          <div className="usermenu">
            <div className="usermenu__head">
              <b>{user?.name}</b>
              <span>{user?.email}</span>
            </div>
            <Link to="/" className="usermenu__item" onClick={() => setUserMenuOpen(false)}>
              <Icon.Home size={15} />
              Back to site
            </Link>
            <Link to={withTeam('/app/settings')} className="usermenu__item" onClick={() => setUserMenuOpen(false)}>
              <Icon.Settings size={15} />
              Settings
            </Link>
            <button
              type="button"
              className="usermenu__item usermenu__item--danger"
              onClick={() => {
                setUserMenuOpen(false)
                signOut()
                navigate('/')
              }}
            >
              <Icon.LogOut size={15} />
              Sign out
            </button>
          </div>
        )}
        <button type="button" className="sidebar__user" aria-expanded={userMenuOpen} onClick={() => setUserMenuOpen((v) => !v)}>
          <span className="dash-avatar dash-avatar--sm">{initials(user?.name ?? '')}</span>
          <span style={{ minWidth: 0, flex: 1 }}>
            <b>{user?.name}</b>
            <span>
              {isAdmin ? 'Admin' : 'Member'} · {org?.name}
            </span>
          </span>
          <Icon.ChevronDown size={14} />
        </button>
      </div>
    </aside>
  )
}

/* -------------------------------------------------------------------
   Top bar
   ------------------------------------------------------------------- */

function TopBar({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const { team, clashes, agents, memory } = useProject()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)
  const notifRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!searchRef.current?.contains(event.target as Node)) setSearchOpen(false)
      if (!notifRef.current?.contains(event.target as Node)) setNotifOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSearchOpen(false)
        setNotifOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const needle = query.trim().toLowerCase()
  const results = useMemo(() => {
    if (!needle) return []
    const hits: { label: string; sub: string; to: string }[] = []
    for (const agent of agents) {
      if (`${agent.name} ${agent.current_claim?.intent_text ?? ''} ${agent.developer_name}`.toLowerCase().includes(needle)) {
        hits.push({ label: agent.name, sub: agent.current_claim?.intent_text ?? 'No open claim', to: `/app/agents/${agent.id}?team=${team.id}` })
      }
    }
    for (const clash of clashes) {
      if (`${clash.title} ${clash.axis} ${clash.shared_concepts.join(' ')}`.toLowerCase().includes(needle)) {
        hits.push({ label: `Conflict: ${clash.title}`, sub: clash.shared_concepts.join(', '), to: `/app/conflicts?team=${team.id}` })
      }
    }
    for (const entry of memory) {
      if (`${entry.content} ${entry.concepts.join(' ')}`.toLowerCase().includes(needle)) {
        hits.push({ label: MEMORY_LABEL[entry.type], sub: entry.content.slice(0, 68) + (entry.content.length > 68 ? '…' : ''), to: `/app/memory?team=${team.id}` })
      }
    }
    return hits.slice(0, 6)
  }, [needle, agents, clashes, memory, team.id])

  const openClashes = clashes.filter(isOpen)

  return (
    <header className="topbar">
      <button type="button" className="icon-btn topbar__burger" aria-label="Open navigation" onClick={onOpenSidebar}>
        <Icon.Menu />
      </button>

      <div className="topbar__search" ref={searchRef}>
        <Icon.Search />
        <input
          className="dash-input"
          placeholder="Search agents, conflicts, memory…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setSearchOpen(true)
          }}
          onFocus={() => setSearchOpen(true)}
        />
        {searchOpen && needle.length > 0 && (
          <div className="popover" style={{ left: 0, right: 'auto', width: '100%' }}>
            {results.length === 0 ? (
              <div className="empty-state" style={{ padding: '28px 16px' }}>
                <b>No matches</b>
                <p>Nothing in {team.name} mentions "{query}". Shared memory can search by meaning.</p>
              </div>
            ) : (
              <div className="popover__list">
                {results.map((result, index) => (
                  <button
                    type="button"
                    className="popover__item"
                    key={`${result.to}-${index}`}
                    onClick={() => {
                      navigate(result.to)
                      setSearchOpen(false)
                      setQuery('')
                    }}
                  >
                    <span className="popover__icon">
                      <Icon.Search size={14} />
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <b>{result.label}</b>
                      <p>{result.sub}</p>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="topbar__spacer" />

      <div className="topbar__actions">
        <ThemeToggle />
        <div className="notif-wrap" ref={notifRef}>
          <button type="button" className="icon-btn" aria-label="Notifications" aria-expanded={notifOpen} onClick={() => setNotifOpen((v) => !v)}>
            <Icon.Bell />
            {openClashes.length > 0 && <span className="bell-dot">{openClashes.length}</span>}
          </button>
          {notifOpen && (
            <div className="popover">
              <div className="popover__head">
                Notifications
                <span className="badge">{openClashes.length} open</span>
              </div>
              <div className="popover__list">
                {openClashes.length === 0 ? (
                  <div className="empty-state" style={{ padding: '32px 16px' }}>
                    <Icon.CheckCircle size={26} />
                    <b>All clear</b>
                    <p>No conflicts are waiting on you.</p>
                  </div>
                ) : (
                  openClashes.map((clash) => (
                    <button
                      type="button"
                      className="popover__item"
                      key={clash.id}
                      onClick={() => {
                        navigate(`/app/conflicts?team=${team.id}`)
                        setNotifOpen(false)
                      }}
                    >
                      <span className="popover__icon" style={{ background: 'var(--danger-soft)', color: 'var(--danger)' }}>
                        <Icon.Alert size={15} />
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>{clash.title}</b>
                        <p>
                          {clash.agent_a} vs {clash.agent_b}
                        </p>
                        <time>{relative(clash.created_at)}</time>
                      </span>
                    </button>
                  ))
                )}
              </div>
              <div className="popover__foot">
                <Link to={`/app/conflicts?team=${team.id}`} className="dash-quiet-button" onClick={() => setNotifOpen(false)}>
                  View all conflicts
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

/* -------------------------------------------------------------------
   Overview
   ------------------------------------------------------------------- */

function AgentRow({ agent }: { agent: Agent }) {
  const { team, agentStatus } = useProject()
  return (
    <Link className="agent-row" to={`/app/agents/${agent.id}?team=${team.id}`}>
      <span className="dash-avatar">{initials(agent.name)}</span>
      <span className="agent-row__main">
        <span className="agent-row__name">
          {agent.name}
          <StatusBadge status={agentStatus(agent)} />
        </span>
        <span className="agent-row__task">{agent.current_claim?.intent_text ?? 'No open claim'}</span>
      </span>
      <span className="agent-row__side">
        {agent.current_claim?.branch && <span className="mono" style={{ fontSize: '0.6875rem' }}>{agent.current_claim.branch}</span>}
        <span style={{ fontSize: '0.6875rem', color: 'var(--text-3)' }}>seen {relative(agent.last_seen)}</span>
      </span>
    </Link>
  )
}

function OverviewPage() {
  const { team, agents, claims, clashes, memory, activity, counters, loading, agentStatus } = useProject()
  const { user, isAdmin } = useSession()
  const [filter, setFilter] = useState<'all' | UiAgentStatus>('all')
  const [query, setQuery] = useState('')

  const openClashes = clashes.filter(isOpen)
  const attention = openClashes[0]
  const activeAgents = agents.filter((a) => agentStatus(a) !== 'idle').length

  const visible = agents.filter((agent) => {
    if (filter !== 'all' && agentStatus(agent) !== filter) return false
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return `${agent.name} ${agent.current_claim?.intent_text ?? ''} ${agent.developer_name}`.toLowerCase().includes(needle)
  })

  const tiles = [
    { label: 'Active agents', value: activeAgents, note: `of ${agents.length} connected`, icon: <Icon.Bot size={16} />, bg: 'var(--info-soft)', fg: 'var(--info)' },
    { label: 'Open claims', value: claims.filter((c) => c.status === 'open').length, note: 'declared, not yet handed off', icon: <Icon.Flag size={16} />, bg: 'var(--success-soft)', fg: 'var(--success)' },
    { label: 'Open conflicts', value: openClashes.length, note: openClashes.length ? 'waiting on a human' : `${counters?.clashes_caught ?? 0} caught so far`, icon: <Icon.Bolt size={16} />, bg: 'var(--danger-soft)', fg: 'var(--danger)' },
    { label: 'Memory entries', value: memory.length, note: counters?.tokens_saved ? `${counters.tokens_saved.toLocaleString()} tokens saved` : 'every agent reads these', icon: <Icon.Brain size={16} />, bg: 'var(--warn-soft)', fg: 'var(--warn)' },
  ]

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>{team.name}</h1>
          <p>
            Welcome back, {firstName(user?.name ?? '')} · {team.repo ?? 'no repository'} · {activeAgents} agent{activeAgents === 1 ? '' : 's'} at work
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {isAdmin && (
            <Link to="/app/members" className="dash-ghost-button">
              <Icon.Users size={15} />
              Manage members
            </Link>
          )}
          <Link to={`/app/conflicts?team=${team.id}`} className="dash-primary-button">
            <Icon.Scale size={15} />
            Arbitrate conflicts
          </Link>
        </div>
      </div>

      <div className="dash-stat-grid">
        {tiles.map((tile) => (
          <div className="dash-stat-card" key={tile.label}>
            <div className="dash-stat-card__top">
              <span className="dash-stat-card__label">{tile.label}</span>
              <span className="dash-stat-card__icon" style={{ background: tile.bg, color: tile.fg }}>
                {tile.icon}
              </span>
            </div>
            <div className="dash-stat-card__value">{loading ? '…' : tile.value}</div>
            <p className="dash-stat-card__note">{tile.note}</p>
          </div>
        ))}
      </div>

      <div className="split">
        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Agents at work</h2>
                <p>What each agent declared it is doing right now.</p>
              </div>
              <div className="dash-search">
                <Icon.Search />
                <input className="dash-input" placeholder="Filter agents" value={query} onChange={(event) => setQuery(event.target.value)} />
              </div>
            </div>
            <div className="panel__body" style={{ paddingBottom: 12 }}>
              <div className="filters">
                {(['all', 'working', 'reviewing', 'blocked', 'idle'] as const).map((key) => (
                  <button type="button" key={key} className={`filter${filter === key ? ' is-active' : ''}`} onClick={() => setFilter(key)}>
                    {key === 'all' ? 'All' : STATUS_LABEL[key]}
                    <span className="filter__n">{key === 'all' ? agents.length : agents.filter((a) => agentStatus(a) === key).length}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="panel__body panel__body--flush">
              {agents.length === 0 ? (
                <div className="empty-state">
                  <Icon.Bot size={28} />
                  <b>No agents connected yet</b>
                  <p>Create an API key in Settings and add the MCP server to your coding agent. It appears here on its first declaration.</p>
                  <Link to={`/app/settings?team=${team.id}`} className="dash-primary-button">
                    <Icon.Key size={15} />
                    Connect an agent
                  </Link>
                </div>
              ) : visible.length === 0 ? (
                <div className="empty-state">
                  <Icon.Inbox />
                  <b>No agents match</b>
                  <p>Try another status, or clear the filter.</p>
                </div>
              ) : (
                visible.map((agent) => <AgentRow agent={agent} key={agent.id} />)
              )}
            </div>
            <div className="panel__foot">
              <span style={{ fontSize: '0.75rem', color: 'var(--text-3)' }}>
                Showing {visible.length} of {agents.length}
              </span>
              <Link to={`/app/agents?team=${team.id}`} className="dash-quiet-button">
                All agents
                <Icon.ArrowRight size={15} />
              </Link>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Recent activity</h2>
                <p>Claims, conflicts and rulings across the team.</p>
              </div>
              <Link to={`/app/activity?team=${team.id}`} className="dash-quiet-button">
                Full timeline
                <Icon.ArrowRight size={15} />
              </Link>
            </div>
            <div className="timeline">
              {activity.length === 0 ? (
                <div className="empty-state">
                  <Icon.Pulse />
                  <b>Quiet so far</b>
                  <p>The first declaration will show up here within a second of it happening.</p>
                </div>
              ) : (
                activity.slice(0, 6).map((event) => <TimelineItem event={event} key={event.id} />)
              )}
            </div>
          </section>
        </div>

        <div className="stack">
          {attention ? (
            <section className="attention">
              <div className="attention__head">
                <Icon.Alert size={16} />
                Needs your attention
              </div>
              <div className="attention__body">
                <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                  <SeverityBadge severity={severityOf(attention)} />
                  <span className="badge">{relative(attention.created_at)}</span>
                </div>
                <h3>{attention.title}</h3>
                <p>{attention.explanation}</p>
                <Link to={`/app/conflicts?team=${team.id}`} className="dash-primary-button">
                  <Icon.Scale size={15} />
                  Review and rule
                </Link>
              </div>
            </section>
          ) : (
            <section className="panel">
              <div className="empty-state">
                <Icon.CheckCircle size={30} />
                <b>Nothing needs you</b>
                <p>No open conflicts. Agents are working from the same rules.</p>
              </div>
            </section>
          )}

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Shared memory</h2>
                <p>The newest things every agent now knows.</p>
              </div>
              <Link to={`/app/memory?team=${team.id}`} className="dash-quiet-button">
                Open
                <Icon.ArrowRight size={15} />
              </Link>
            </div>
            <div className="panel__body panel__body--flush">
              {memory.length === 0 ? (
                <div className="empty-state">
                  <Icon.Brain size={26} />
                  <b>Nothing recorded yet</b>
                  <p>Agents write discoveries, decisions and dead ends here as they work.</p>
                </div>
              ) : (
                memory.slice(0, 3).map((entry) => <MemoryItem entry={entry} key={entry.id} compact />)
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function TimelineItem({ event }: { event: ActivityItem }) {
  const tone = event.kind === 'clash' ? 'clash' : event.kind === 'ruling' ? 'ruling' : event.kind === 'claim' || event.kind === 'pr' ? 'claim' : ''
  const glyph =
    event.kind === 'clash' ? <Icon.Alert size={15} /> : event.kind === 'ruling' ? <Icon.Scale size={15} /> : event.kind === 'claim' ? <Icon.Flag size={15} /> : event.kind === 'pr' ? <Icon.Git size={15} /> : <Icon.Brain size={15} />
  return (
    <div className="tl-item">
      <span className={`tl-dot${tone ? ` tl-dot--${tone}` : ''}`}>{glyph}</span>
      <div className="tl-body">
        <b>{event.title}</b>
        <p>{event.detail}</p>
        <time>
          {clockTime(event.at)} · {relative(event.at)}
        </time>
      </div>
    </div>
  )
}

function MemoryItem({ entry, compact = false, fresh = false }: { entry: MemoryEntry; compact?: boolean; fresh?: boolean }) {
  const body = compact && entry.content.length > 150 ? `${entry.content.slice(0, 150)}…` : entry.content
  return (
    <article className={`mem-item${fresh ? ' is-new' : ''}`}>
      <div className="mem-item__top">
        <span className={`badge badge--${entry.type}`}>{MEMORY_LABEL[entry.type]}</span>
        <span className="mem-item__concepts">{entry.concepts.join(' · ') || entry.title}</span>
        {fresh && (
          <span className="badge badge--working">
            <span className="badge__dot" />
            Just saved
          </span>
        )}
      </div>
      <p className="mem-item__body">{body}</p>
      <div className="mem-item__foot">
        <span>{entry.source_agent ?? (entry.type === 'ruling' ? 'Human ruling' : 'Consensus')}</span>
        <span>{relative(entry.created_at)}</span>
      </div>
    </article>
  )
}

/* -------------------------------------------------------------------
   Agents
   ------------------------------------------------------------------- */

function AgentsPage() {
  const { team, agents, claims, agentStatus } = useProject()
  const [filter, setFilter] = useState<'all' | UiAgentStatus>('all')
  const [query, setQuery] = useState('')

  const visible = agents.filter((agent) => {
    if (filter !== 'all' && agentStatus(agent) !== filter) return false
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return `${agent.name} ${agent.current_claim?.intent_text ?? ''} ${agent.developer_name}`.toLowerCase().includes(needle)
  })

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Agents</h1>
          <p>
            {agents.length} agent{agents.length === 1 ? ' has' : 's have'} connected to {team.name}.
          </p>
        </div>
        <div className="dash-search">
          <Icon.Search />
          <input className="dash-input" placeholder="Search agents" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </div>

      <div className="filters" style={{ marginBottom: 18 }}>
        {(['all', 'working', 'reviewing', 'blocked', 'idle'] as const).map((key) => (
          <button type="button" key={key} className={`filter${filter === key ? ' is-active' : ''}`} onClick={() => setFilter(key)}>
            {key === 'all' ? 'All' : STATUS_LABEL[key]}
            <span className="filter__n">{key === 'all' ? agents.length : agents.filter((a) => agentStatus(a) === key).length}</span>
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <EmptyPanel
          icon={<Icon.Bot size={28} />}
          title={agents.length === 0 ? 'No agents yet' : 'No agents match'}
          body={agents.length === 0 ? 'Connect one from Settings → API keys. It appears here on its first declaration.' : 'Change the filter or clear the search.'}
          action={
            agents.length === 0 ? (
              <Link to={`/app/settings?team=${team.id}`} className="dash-primary-button">
                <Icon.Key size={15} />
                Connect an agent
              </Link>
            ) : undefined
          }
        />
      ) : (
        <div className="agent-grid">
          {visible.map((agent) => {
            const claim = agent.current_claim ? claims.find((c) => c.id === agent.current_claim!.id) : undefined
            return (
              <Link className="agent-card" to={`/app/agents/${agent.id}?team=${team.id}`} key={agent.id}>
                <div className="agent-card__top">
                  <span className="dash-avatar">{initials(agent.name)}</span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <h3>{agent.name}</h3>
                    <div className="agent-card__dev">{agent.developer_name}</div>
                  </div>
                  <StatusBadge status={agentStatus(agent)} />
                </div>
                <p className="agent-card__task">{agent.current_claim?.intent_text ?? 'No open claim'}</p>
                {claim && <ConceptChips concepts={claim.concepts} />}
                <div style={{ marginTop: 'auto' }}>
                  <div className="agent-card__meta">
                    <span className="mono" style={{ fontSize: '0.6875rem' }}>{agent.current_claim?.branch ?? '—'}</span>
                    <span>{agent.open_claims} open</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, fontSize: '0.6875rem', color: 'var(--text-3)' }}>
                    <span>Last seen {relative(agent.last_seen)}</span>
                    {agent.current_claim?.pr_number && <span>PR #{agent.current_claim.pr_number}</span>}
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

function StanceList({ claim }: { claim: Claim }) {
  return (
    <dl className="kv">
      {AXES.map((axis) => (
        <div key={axis.key} style={{ display: 'contents' }}>
          <dt>{axis.label}</dt>
          <dd style={{ color: claim.stance[axis.key] ? 'var(--text)' : 'var(--text-3)' }}>{claim.stance[axis.key] ?? 'Not addressed by this plan'}</dd>
        </div>
      ))}
    </dl>
  )
}

function AgentDetailPage() {
  const { agentId } = useParams()
  const { team, agents, claims, clashes, agentById, agentStatus, withdrawClaim } = useProject()
  const { user, isAdmin } = useSession()
  const { busy, error, run } = useAction()
  const agent = agentId ? agentById(agentId) : undefined

  if (!agent) {
    return (
      <div className="page">
        <EmptyPanel
          title={`No such agent in ${team.name}`}
          body="It may have been removed, or the link points at another team."
          action={
            <Link to={`/app/agents?team=${team.id}`} className="dash-primary-button">
              Back to agents
            </Link>
          }
        />
      </div>
    )
  }

  const agentClaims = claims.filter((claim) => claim.agent_id === agent.id)
  const claimIds = new Set(agentClaims.map((c) => c.id))
  const related = clashes.filter((c) => claimIds.has(c.claim_a_id) || claimIds.has(c.claim_b_id))
  const current = agentClaims.find((claim) => claim.status === 'open') ?? agentClaims.find((claim) => claim.status === 'in_review')
  const canWithdraw = current?.status === 'open' && (isAdmin || agent.user_id === user?.id)

  return (
    <div className="page">
      <Link to={`/app/agents?team=${team.id}`} className="crumb">
        <Icon.ArrowLeft />
        Agents
      </Link>

      <div className="page__head">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          <span className="dash-avatar" style={{ width: 46, height: 46, fontSize: '0.9375rem' }}>
            {initials(agent.name)}
          </span>
          <div>
            <h1>{agent.name}</h1>
            <p>
              {agent.developer_name} · last seen {relative(agent.last_seen)}
            </p>
          </div>
        </div>
        <StatusBadge status={agentStatus(agent)} />
      </div>

      {error && <DashNotice tone="danger">{error}</DashNotice>}

      <div className="split">
        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Declared plan</h2>
                <p>{current ? current.intent_text : 'This agent has no open claim.'}</p>
              </div>
              {current && <ClaimStatusBadge status={current.status} />}
            </div>
            {current && (
              <div className="panel__body">
                {current.stance.summary && <p style={{ fontSize: '0.875rem', color: 'var(--text-2)', marginBottom: 14 }}>{current.stance.summary}</p>}
                <ConceptChips concepts={current.concepts} />
                <div style={{ marginTop: 14 }}>
                  <StanceList claim={current} />
                </div>
                {canWithdraw && (
                  <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      className="dash-ghost-button"
                      disabled={busy}
                      onClick={() => run(() => withdrawClaim(current.id, `Withdrawn from the dashboard by ${user?.name ?? 'an admin'}`))}
                    >
                      {busy ? <Busy label="Withdrawing…" /> : 'Withdraw this claim'}
                    </button>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel__head">
              <h2>Claims</h2>
              <span className="badge">{agentClaims.length}</span>
            </div>
            <div className="panel__body panel__body--flush">
              {agentClaims.length === 0 ? (
                <div className="empty-state">
                  <b>No claims filed</b>
                  <p>This agent has not declared any intent yet.</p>
                </div>
              ) : (
                agentClaims.map((claim) => (
                  <div className="mem-item" key={claim.id}>
                    <div className="mem-item__top">
                      <ClaimStatusBadge status={claim.status} />
                      <span className="mem-item__concepts">{claim.intent_text}</span>
                    </div>
                    <ConceptChips concepts={claim.concepts} />
                    <div className="mem-item__foot">
                      <span className="mono">{claim.branch ?? 'no branch'}</span>
                      {claim.pr_number && <span>PR #{claim.pr_number}</span>}
                      <span>{relative(claim.created_at)}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <h2>Details</h2>
            </div>
            <div className="panel__body">
              <dl className="kv">
                <dt>Developer</dt>
                <dd>{agent.developer_name}</dd>
                <dt>Branch</dt>
                <dd className="mono">{agent.current_claim?.branch ?? '—'}</dd>
                <dt>Open claims</dt>
                <dd>{agent.open_claims}</dd>
                <dt>Task</dt>
                <dd>{agent.current_claim?.task_ref ?? '—'}</dd>
                <dt>Last seen</dt>
                <dd>{relative(agent.last_seen)}</dd>
              </dl>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <h2>Related conflicts</h2>
              <span className="badge">{related.length}</span>
            </div>
            <div className="panel__body panel__body--flush">
              {related.length === 0 ? (
                <div className="empty-state">
                  <Icon.CheckCircle size={26} />
                  <b>No conflicts</b>
                  <p>Nothing this agent claimed overlaps another agent's work.</p>
                </div>
              ) : (
                related.map((clash) => (
                  <Link className="mem-item" to={`/app/conflicts?team=${team.id}`} key={clash.id}>
                    <div className="mem-item__top">
                      <SeverityBadge severity={severityOf(clash)} />
                      <span className="mem-item__concepts">{clash.title}</span>
                      <span className={`badge badge--${isOpen(clash) ? 'blocked' : 'working'}`}>{isOpen(clash) ? 'open' : 'resolved'}</span>
                    </div>
                    <div className="mem-item__foot">
                      <span>vs {clash.agent_a === agent.name ? clash.agent_b : clash.agent_a}</span>
                      <span>{relative(clash.created_at)}</span>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <h2>Other agents</h2>
            </div>
            <div className="panel__body panel__body--flush">
              {agents.filter((other) => other.id !== agent.id).map((other) => (
                <Link className="agent-row" to={`/app/agents/${other.id}?team=${team.id}`} key={other.id}>
                  <span className="dash-avatar dash-avatar--sm">{initials(other.name)}</span>
                  <span className="agent-row__main">
                    <span className="agent-row__name">{other.name}</span>
                    <span className="agent-row__task">{other.current_claim?.intent_text ?? 'No open claim'}</span>
                  </span>
                  <StatusBadge status={agentStatus(other)} />
                </Link>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------
   Conflicts
   ------------------------------------------------------------------- */

const RESOLUTION_COPY: Record<Resolution, { title: (a: string, b: string) => string; sub: string }> = {
  a_proceeds: { title: (a) => `${a} proceeds`, sub: 'The other claim waits until this work lands.' },
  b_proceeds: { title: (_a, b) => `${b} proceeds`, sub: 'The other claim waits until this work lands.' },
  both_with_note: { title: () => 'Both proceed, with a note', sub: 'Compatible work. Record the constraint they must both respect.' },
}

function ConflictsPage() {
  const { clashes } = useProject()
  const [filter, setFilter] = useState<'open' | 'resolved' | 'all'>('open')

  const visible = clashes.filter((clash) => filter === 'all' || (filter === 'open' ? isOpen(clash) : !isOpen(clash)))
  const openCount = clashes.filter(isOpen).length

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Conflicts</h1>
          <p>{openCount === 0 ? 'Nothing is waiting on a ruling.' : `${openCount} conflict${openCount === 1 ? '' : 's'} waiting on a ruling.`}</p>
        </div>
      </div>

      <div className="filters" style={{ marginBottom: 18 }}>
        {(['open', 'resolved', 'all'] as const).map((key) => (
          <button type="button" key={key} className={`filter${filter === key ? ' is-active' : ''}`} onClick={() => setFilter(key)}>
            {key[0]!.toUpperCase() + key.slice(1)}
            <span className="filter__n">{key === 'all' ? clashes.length : clashes.filter((c) => (key === 'open' ? isOpen(c) : !isOpen(c))).length}</span>
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <EmptyPanel
          icon={<Icon.CheckCircle size={30} />}
          title="Nothing here"
          body={filter === 'open' ? 'Every conflict has a ruling. Agents are working from the same rules.' : 'No conflicts match this filter.'}
        />
      ) : (
        visible.map((clash) => <ClashCard clash={clash} key={clash.id} />)
      )}
    </div>
  )
}

function VersusSide({ name, intent, position, axis, branch, developer }: { name: string; intent: string; position: string | null; axis: string; branch: string | null; developer?: string }) {
  return (
    <div className="versus__side">
      <div className="versus__who">
        <span className="dash-avatar dash-avatar--sm">{initials(name)}</span>
        <div>
          <b>{name}</b>
          <span>{developer ?? ''}</span>
        </div>
      </div>
      <div className="versus__intent">{intent}</div>
      <p className="versus__position">{position ?? `Takes no explicit position on ${axis.replace(/_/g, ' ')}.`}</p>
      {branch && <span className="chip">{branch}</span>}
    </div>
  )
}

function ClashCard({ clash }: { clash: Clash }) {
  const { team, agents, claimById, resolveClash } = useProject()
  const { isRestricted } = useSession()
  const { busy, error, run } = useAction()
  const [choice, setChoice] = useState<Resolution | null>(null)
  const [note, setNote] = useState('')

  const nameA = clash.agent_a ?? 'Agent A'
  const nameB = clash.agent_b ?? 'Agent B'
  const devA = agents.find((a) => a.name === clash.agent_a)?.developer_name
  const devB = agents.find((a) => a.name === clash.agent_b)?.developer_name
  const open = isOpen(clash)

  return (
    <article className={`clash-card${open ? ' clash-card--open' : ''}`}>
      <div className="clash-card__head">
        <div>
          <h3>{clash.title}</h3>
          <p>
            {nameA} vs {nameB} · opened {relative(clash.created_at)} · {clash.shared_concepts.join(', ')}
          </p>
        </div>
        <div className="clash-card__badges">
          <SeverityBadge severity={severityOf(clash)} />
          <span className={`badge badge--${open ? 'blocked' : 'working'}`}>{open ? 'Open' : clash.status === 'auto_resolved' ? 'Auto-resolved' : 'Resolved'}</span>
        </div>
      </div>

      <div className="versus">
        <VersusSide name={nameA} developer={devA} intent={clash.intent_a ?? ''} position={clash.position_a} axis={clash.axis} branch={claimById(clash.claim_a_id)?.branch ?? null} />
        <div className="versus__mid">
          <span>VS</span>
        </div>
        <VersusSide name={nameB} developer={devB} intent={clash.intent_b ?? ''} position={clash.position_b} axis={clash.axis} branch={claimById(clash.claim_b_id)?.branch ?? null} />
      </div>

      <div className="explain">
        <Icon.Info size={16} />
        <div>
          <b style={{ display: 'block', marginBottom: 4, color: 'var(--text)' }}>Why this fired</b>
          {clash.explanation}
        </div>
      </div>

      {!open ? (
        <div className="resolved-box">
          <Icon.CheckCircle />
          <div>
            <b>{clash.resolution ? RESOLUTION_COPY[clash.resolution].title(nameA, nameB) : 'Resolved'}</b>
            <p>{clash.resolution_note}</p>
            <small>
              {clash.status === 'auto_resolved' ? 'Resolved automatically' : `Ruled by ${clash.resolved_by ?? 'a human'}`} · written to shared memory
            </small>
          </div>
        </div>
      ) : isRestricted ? (
        <div className="arbitrate">
          <DashNotice tone="warn">Your account is restricted, so you can read this conflict but not rule on it. Ask an admin to lift the restriction.</DashNotice>
        </div>
      ) : (
        <div className="arbitrate">
          <h4>Your ruling</h4>
          {(['a_proceeds', 'b_proceeds', 'both_with_note'] as const).map((key) => (
            <label className={`option${choice === key ? ' is-checked' : ''}`} key={key}>
              <input type="radio" name={`resolution-${clash.id}`} value={key} checked={choice === key} onChange={() => setChoice(key)} />
              <span className="option__mark" />
              <span>
                <b>{RESOLUTION_COPY[key].title(nameA, nameB)}</b>
                <span>{RESOLUTION_COPY[key].sub}</span>
              </span>
            </label>
          ))}
          <label style={{ display: 'block', marginTop: 14 }}>
            <span style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-3)', marginBottom: 6 }}>
              Note {choice === 'both_with_note' ? '(required)' : '(optional)'}
            </span>
            <textarea className="dash-textarea" placeholder="Explain the constraint both agents must respect from now on…" value={note} onChange={(event) => setNote(event.target.value)} />
          </label>
          {error && <DashNotice tone="danger">{error}</DashNotice>}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginTop: 14, flexWrap: 'wrap' }}>
            <Link to={`/app/memory?team=${team.id}`} style={{ fontSize: '0.75rem', color: 'var(--text-3)' }}>
              Saving writes a ruling to shared memory and releases the waiting agent.
            </Link>
            <button
              type="button"
              className="dash-primary-button"
              disabled={busy || !choice || (choice === 'both_with_note' && !note.trim())}
              onClick={() => choice && run(() => resolveClash(clash.id, choice, note.trim()))}
            >
              {busy ? <Busy label="Saving…" /> : (
                <>
                  <Icon.Scale size={15} />
                  Save ruling
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </article>
  )
}

/* -------------------------------------------------------------------
   Shared memory
   ------------------------------------------------------------------- */

function MemoryPage() {
  const { team, memory, justSavedMemoryId, writeMemory } = useProject()
  const { user, isRestricted } = useSession()
  const [type, setType] = useState<'all' | MemoryType>('all')
  const [query, setQuery] = useState('')
  const [semantic, setSemantic] = useState<MemoryEntry[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<{ type: MemoryType; content: string; concepts: string }>({ type: 'decision', content: '', concepts: '' })
  const { busy, error, run } = useAction()

  const needle = query.trim().toLowerCase()
  const source = semantic ?? memory
  const visible = source.filter((entry) => {
    if (type !== 'all' && entry.type !== type) return false
    if (semantic || !needle) return true
    return `${entry.content} ${entry.concepts.join(' ')} ${entry.source_agent ?? ''}`.toLowerCase().includes(needle)
  })

  const searchByMeaning = async () => {
    if (!needle) return
    setSearching(true)
    try {
      setSemantic(await projectApi.memory(team.id, { q: query.trim(), limit: 50 }))
    } catch {
      setSemantic(null)
    } finally {
      setSearching(false)
    }
  }

  const types: ('all' | MemoryType)[] = ['all', 'ruling', 'decision', 'discovery', 'dead_end', 'handoff']

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Shared memory</h1>
          <p>Every agent reads this before it plans. {memory.length} entries.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <form
            className="dash-search"
            onSubmit={(event) => {
              event.preventDefault()
              void searchByMeaning()
            }}
          >
            <Icon.Search />
            <input
              className="dash-input"
              placeholder="Search memory… Enter for search by meaning"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setSemantic(null)
              }}
            />
          </form>
          {!isRestricted && (
            <button type="button" className="dash-primary-button" onClick={() => setShowForm((v) => !v)}>
              <Icon.Plus />
              Add entry
            </button>
          )}
        </div>
      </div>

      {showForm && (
        <section className="panel" style={{ marginBottom: 18 }}>
          <div className="panel__head">
            <div>
              <h2>Record something for every agent</h2>
              <p>One to three sentences. Specific and reusable. Near-duplicates are linked, not repeated.</p>
            </div>
          </div>
          <div className="panel__body">
            <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 2fr)' }}>
              <label className="dash-field">
                <span className="dash-field__label">Type</span>
                <select className="dash-select" value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value as MemoryType })}>
                  <option value="decision">Decision</option>
                  <option value="discovery">Discovery</option>
                  <option value="dead_end">Dead end</option>
                </select>
              </label>
              <label className="dash-field">
                <span className="dash-field__label">Concepts (comma separated)</span>
                <input className="dash-input" placeholder="session model, login endpoint" value={form.concepts} onChange={(event) => setForm({ ...form, concepts: event.target.value })} />
              </label>
            </div>
            <label className="dash-field">
              <span className="dash-field__label">Content</span>
              <textarea className="dash-textarea" placeholder="All auth failures return 401 with a JSON body. Never redirect from the API." value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} />
            </label>
            {error && <DashNotice tone="danger">{error}</DashNotice>}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button type="button" className="dash-ghost-button" onClick={() => setShowForm(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="dash-primary-button"
                disabled={busy || form.content.trim().length < 8}
                onClick={() =>
                  run(async () => {
                    await writeMemory({
                      type: form.type,
                      content: form.content.trim(),
                      concepts: form.concepts.split(',').map((c) => c.trim()).filter(Boolean),
                      author: user?.name ?? 'Human',
                    })
                    setForm({ type: 'decision', content: '', concepts: '' })
                    setShowForm(false)
                  })
                }
              >
                {busy ? <Busy label="Saving…" /> : 'Save to memory'}
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="filters" style={{ marginBottom: 18 }}>
        {types.map((key) => (
          <button type="button" key={key} className={`filter${type === key ? ' is-active' : ''}`} onClick={() => setType(key)}>
            {key === 'all' ? 'All' : MEMORY_LABEL[key]}
            <span className="filter__n">{key === 'all' ? source.length : source.filter((e) => e.type === key).length}</span>
          </button>
        ))}
        {semantic && (
          <span className="badge badge--working" style={{ marginLeft: 'auto' }}>
            <span className="badge__dot" />
            Ranked by meaning for "{query.trim()}"
          </span>
        )}
        {searching && <span className="badge">Searching…</span>}
      </div>

      <section className="panel">
        <div className="panel__body panel__body--flush">
          {visible.length === 0 ? (
            <div className="empty-state">
              <Icon.Inbox />
              <b>{memory.length === 0 ? 'Nothing recorded yet' : 'Nothing matches'}</b>
              <p>{memory.length === 0 ? 'Agents write here as they work. You can add a decision yourself with "Add entry".' : 'Press Enter to search by meaning instead of by substring.'}</p>
            </div>
          ) : (
            visible.map((entry) => <MemoryItem entry={entry} key={entry.id} fresh={entry.id === justSavedMemoryId} />)
          )}
        </div>
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------
   Activity
   ------------------------------------------------------------------- */

function ActivityPage() {
  const { activity } = useProject()
  const [kind, setKind] = useState<'all' | ActivityKind>('all')

  const visible = activity.filter((event) => kind === 'all' || event.kind === kind)
  const groups: { day: string; items: ActivityItem[] }[] = []
  for (const event of visible) {
    const day = dayLabel(event.at)
    const last = groups[groups.length - 1]
    if (last && last.day === day) last.items.push(event)
    else groups.push({ day, items: [event] })
  }

  const kinds: ('all' | ActivityKind)[] = ['all', 'claim', 'clash', 'ruling', 'memory', 'pr', 'handoff']
  const kindLabel: Record<ActivityKind, string> = { claim: 'Claims', clash: 'Conflicts', ruling: 'Rulings', memory: 'Memory', pr: 'Pull requests', handoff: 'Handoffs' }

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Activity</h1>
          <p>Everything that happened in this team, newest first. Live.</p>
        </div>
      </div>

      <div className="filters" style={{ marginBottom: 18 }}>
        {kinds.map((key) => (
          <button type="button" key={key} className={`filter${kind === key ? ' is-active' : ''}`} onClick={() => setKind(key)}>
            {key === 'all' ? 'Everything' : kindLabel[key]}
          </button>
        ))}
      </div>

      <section className="panel">
        <div className="timeline">
          {groups.length === 0 ? (
            <div className="empty-state">
              <Icon.Inbox />
              <b>Nothing of that kind yet</b>
              <p>{activity.length === 0 ? 'The first declaration will show up here within a second.' : 'Try another filter.'}</p>
            </div>
          ) : (
            groups.map((group) => (
              <div key={group.day}>
                <div className="tl-day">{group.day}</div>
                {group.items.map((event) => (
                  <TimelineItem event={event} key={event.id} />
                ))}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------
   Claims
   ------------------------------------------------------------------- */

function ClaimsPage() {
  const { team, claims, agents, withdrawClaim } = useProject()
  const { user, isAdmin } = useSession()
  const [status, setStatus] = useState<'all' | Claim['status']>('all')
  const [agentName, setAgentName] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [verdicts, setVerdicts] = useState<VerdictLog[]>([])
  const { busy, error, run } = useAction()

  useEffect(() => {
    projectApi.verdicts(team.id, 200).then(setVerdicts).catch(() => setVerdicts([]))
  }, [team.id, claims.length])

  const visible = claims.filter((c) => (status === 'all' || c.status === status) && (!agentName || c.agent_name === agentName))
  const selected = claims.find((c) => c.id === selectedId) ?? null
  const selectedVerdicts = selected ? verdicts.filter((v) => v.claim_id === selected.id) : []
  const owner = selected ? agents.find((a) => a.id === selected.agent_id) : undefined
  const canWithdraw = selected?.status === 'open' && (isAdmin || owner?.user_id === user?.id)

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Claims</h1>
          <p>Every declared intent, with the stance Consensus extracted from it. This is the table that explains why a conflict fired.</p>
        </div>
      </div>

      <div className="filters" style={{ marginBottom: 18, alignItems: 'center' }}>
        {(['all', 'open', 'in_review', 'retired'] as const).map((key) => (
          <button type="button" key={key} className={`filter${status === key ? ' is-active' : ''}`} onClick={() => setStatus(key)}>
            {key === 'all' ? 'All' : CLAIM_LABEL[key]}
            <span className="filter__n">{key === 'all' ? claims.length : claims.filter((c) => c.status === key).length}</span>
          </button>
        ))}
        <select className="dash-select" style={{ marginLeft: 'auto', height: 34, width: 180 }} value={agentName} onChange={(event) => setAgentName(event.target.value)}>
          <option value="">Every agent</option>
          {agents.map((a) => (
            <option key={a.id} value={a.name}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <section className="panel">
        <div className="panel__body panel__body--flush table-scroll">
          {visible.length === 0 ? (
            <div className="empty-state">
              <Icon.Flag size={28} />
              <b>No claims</b>
              <p>{claims.length === 0 ? 'Agents file a claim with declare_intent before they write code. None have yet.' : 'Nothing matches this filter.'}</p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Intent</th>
                  <th>Concepts</th>
                  <th>Branch</th>
                  <th>PR</th>
                  <th>Status</th>
                  <th>Declared</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((claim) => (
                  <tr key={claim.id} onClick={() => setSelectedId(claim.id === selectedId ? null : claim.id)} style={{ cursor: 'pointer', background: claim.id === selectedId ? 'var(--surface-2)' : undefined }}>
                    <td>
                      <div className="cell-strong">{claim.agent_name}</div>
                      <div className="cell-sub">{claim.developer_name}</div>
                    </td>
                    <td className="cell-strong" style={{ maxWidth: 360 }}>{claim.intent_text}</td>
                    <td className="cell-sub">{claim.concepts.slice(0, 4).join(', ') || '—'}</td>
                    <td className="mono cell-sub">{claim.branch ?? '—'}</td>
                    <td className="cell-sub">{claim.pr_number ? `#${claim.pr_number}` : '—'}</td>
                    <td>
                      <ClaimStatusBadge status={claim.status} />
                    </td>
                    <td className="cell-sub">{relative(claim.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {selected && (
        <section className="panel" style={{ marginTop: 18 }}>
          <div className="panel__head">
            <div>
              <h2>{selected.intent_text}</h2>
              <p>
                {selected.agent_name} · {selected.developer_name} · {relative(selected.created_at)}
                {selected.task_ref ? ` · task ${selected.task_ref}` : ''}
              </p>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <ClaimStatusBadge status={selected.status} />
              {canWithdraw && (
                <button type="button" className="dash-ghost-button" disabled={busy} onClick={() => run(() => withdrawClaim(selected.id, `Withdrawn from the dashboard by ${user?.name ?? 'an admin'}`))}>
                  {busy ? <Busy label="Withdrawing…" /> : 'Withdraw'}
                </button>
              )}
            </div>
          </div>
          <div className="panel__body">
            {error && <DashNotice tone="danger">{error}</DashNotice>}
            {selected.stance.summary && <p style={{ fontSize: '0.875rem', color: 'var(--text-2)', marginBottom: 14 }}>{selected.stance.summary}</p>}
            <ConceptChips concepts={selected.concepts} />
            <div style={{ marginTop: 14 }}>
              <StanceList claim={selected} />
            </div>

            <h3 style={{ fontSize: '0.875rem', margin: '20px 0 8px' }}>Verdict log</h3>
            {selectedVerdicts.length === 0 ? (
              <p style={{ fontSize: '0.8125rem', color: 'var(--text-3)' }}>No verdict recorded for this claim.</p>
            ) : (
              selectedVerdicts.map((v) => <VerdictBlock verdict={v} key={v.id} />)
            )}
          </div>
        </section>
      )}
    </div>
  )
}

function VerdictBlock({ verdict }: { verdict: VerdictLog }) {
  const [open, setOpen] = useState(false)
  const tone = verdict.verdict === 'wait' ? 'blocked' : verdict.verdict === 'proceed' ? 'working' : 'reviewing'
  return (
    <div className="mem-item" style={{ padding: '12px 0' }}>
      <div className="mem-item__top">
        <span className={`badge badge--${tone}`}>{verdict.verdict.replace(/_/g, ' ')}</span>
        <span className="mem-item__concepts">{verdict.duration_ms} ms · {relative(verdict.created_at)}</span>
        <button type="button" className="dash-quiet-button" onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide inputs' : 'Show inputs'}
        </button>
      </div>
      {open && (
        <pre className="mono" style={{ fontSize: '0.6875rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--surface-2)', padding: 12, borderRadius: 8, maxHeight: 320, overflow: 'auto' }}>
          {JSON.stringify(verdict.detail, null, 2)}
        </pre>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------
   Tasks
   ------------------------------------------------------------------- */

const TASK_LABEL: Record<TaskStatus, string> = { open: 'Open', in_progress: 'In progress', done: 'Done' }

function TasksPage() {
  const { team, tasks, setTasks, agents, refresh } = useProject()
  const { org, isRestricted } = useSession()
  const [filter, setFilter] = useState<'all' | TaskStatus>('all')
  const [title, setTitle] = useState('')
  const [ref, setRef] = useState('')
  const { busy, error, run } = useAction()
  const sync = useAction()
  const [syncNote, setSyncNote] = useState<string | null>(null)

  const visible = tasks.filter((t) => filter === 'all' || t.status === filter)

  const updateTask = (task: Task, body: Parameters<typeof projectApi.updateTask>[2]) =>
    run(async () => {
      const updated = await projectApi.updateTask(team.id, task.id, body)
      setTasks((current) => current.map((t) => (t.id === task.id ? updated : t)))
    })

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Tasks</h1>
          <p>Work the team planned. Agents reference a task by its id when they declare, so claims link back here.</p>
        </div>
        {org?.notionConnected && (
          <button
            type="button"
            className="dash-ghost-button"
            disabled={sync.busy}
            onClick={() =>
              sync.run(async () => {
                const out = await projectApi.syncNotion(team.id)
                setSyncNote(`${out.tasks_upserted} task${out.tasks_upserted === 1 ? '' : 's'} synced from Notion.`)
                await refresh()
              })
            }
          >
            {sync.busy ? <Busy label="Syncing…" /> : 'Sync from Notion'}
          </button>
        )}
      </div>

      {(syncNote || sync.error) && <DashNotice tone={sync.error ? 'danger' : 'success'}>{sync.error ?? syncNote}</DashNotice>}

      {!isRestricted && (
        <section className="panel" style={{ marginBottom: 18 }}>
          <form
            className="panel__body"
            style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 1fr) auto', alignItems: 'end' }}
            onSubmit={(event) => {
              event.preventDefault()
              if (!title.trim()) return
              void run(async () => {
                const created = await projectApi.createTask(team.id, { title: title.trim(), external_ref: ref.trim() || undefined })
                setTasks((current) => [created, ...current])
                setTitle('')
                setRef('')
              })
            }}
          >
            <label className="dash-field" style={{ marginBottom: 0 }}>
              <span className="dash-field__label">New task</span>
              <input className="dash-input" placeholder="Add rate limiting to the login endpoint" value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="dash-field" style={{ marginBottom: 0 }}>
              <span className="dash-field__label">Reference (optional)</span>
              <input className="dash-input mono" placeholder="ENG-1234" value={ref} onChange={(event) => setRef(event.target.value)} />
            </label>
            <button type="submit" className="dash-primary-button" disabled={busy || !title.trim()}>
              {busy ? <Busy label="Adding…" /> : (
                <>
                  <Icon.Plus />
                  Add
                </>
              )}
            </button>
          </form>
        </section>
      )}

      {error && <DashNotice tone="danger">{error}</DashNotice>}

      <div className="filters" style={{ marginBottom: 18 }}>
        {(['all', 'open', 'in_progress', 'done'] as const).map((key) => (
          <button type="button" key={key} className={`filter${filter === key ? ' is-active' : ''}`} onClick={() => setFilter(key)}>
            {key === 'all' ? 'All' : TASK_LABEL[key]}
            <span className="filter__n">{key === 'all' ? tasks.length : tasks.filter((t) => t.status === key).length}</span>
          </button>
        ))}
      </div>

      <section className="panel">
        <div className="panel__body panel__body--flush table-scroll">
          {visible.length === 0 ? (
            <div className="empty-state">
              <Icon.Calendar size={28} />
              <b>No tasks</b>
              <p>{tasks.length === 0 ? 'Add one above, or connect Notion in Integrations and sync a database.' : 'Nothing matches this filter.'}</p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Reference</th>
                  <th>Status</th>
                  <th>Assignee</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map((task) => (
                  <tr key={task.id}>
                    <td className="cell-strong">{task.title}</td>
                    <td className="mono cell-sub">{task.external_ref ?? '—'}</td>
                    <td>
                      <select className="dash-select" style={{ height: 34, width: 140 }} value={task.status} disabled={isRestricted} onChange={(event) => updateTask(task, { status: event.target.value as TaskStatus })}>
                        {(['open', 'in_progress', 'done'] as const).map((s) => (
                          <option key={s} value={s}>
                            {TASK_LABEL[s]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select className="dash-select" style={{ height: 34, width: 160 }} value={task.assignee_agent ?? ''} disabled={isRestricted} onChange={(event) => updateTask(task, { assignee_agent: event.target.value })}>
                        <option value="">Unassigned</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.name}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {!isRestricted && (
                        <button
                          type="button"
                          className="icon-btn icon-btn--danger"
                          aria-label={`Delete ${task.title}`}
                          onClick={() =>
                            run(async () => {
                              await projectApi.deleteTask(team.id, task.id)
                              setTasks((current) => current.filter((t) => t.id !== task.id))
                            })
                          }
                        >
                          <Icon.Trash />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  )
}

/* -------------------------------------------------------------------
   Integrations
   ------------------------------------------------------------------- */

function WebhookLine({ status }: { status: WebhookStatus | null | undefined }) {
  if (!status) return null
  return status.registered ? (
    <DashNotice tone="success">Merge webhook registered on the repository. Merged pull requests retire their claims automatically.</DashNotice>
  ) : (
    <DashNotice tone="warn">Webhook not registered: {status.reason}</DashNotice>
  )
}

function IntegrationsPage() {
  const { team, refresh } = useProject()
  const { org, user, isAdmin, teamById, connectGithub, disconnectGithub, connectNotion, disconnectNotion, updateTeam } = useSession()
  const gh = useAction()
  const notion = useAction()
  const hook = useAction()
  const [notionForm, setNotionForm] = useState({ token: '', databaseId: '' })
  const [syncNote, setSyncNote] = useState<string | null>(null)
  const [hookStatus, setHookStatus] = useState<WebhookStatus | null>(null)
  const current = teamById(team.id) ?? team

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Integrations</h1>
          <p>GitHub for repositories and pull requests, Notion for tasks. Connections belong to {org?.name}; the repository belongs to this team.</p>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>GitHub</h2>
                <p>{org?.githubConnected ? 'Connected. Handoffs open pull requests and rulings become PR comments.' : 'Not connected. An admin who signed in with GitHub can connect it in one click.'}</p>
              </div>
              <span className={`badge badge--${org?.githubConnected ? 'ok' : 'muted'}`}>{org?.githubConnected ? 'Connected' : 'Off'}</span>
            </div>
            <div className="panel__body">
              {gh.error && <DashNotice tone="danger">{gh.error}</DashNotice>}
              {syncNote && <DashNotice tone="success">{syncNote}</DashNotice>}
              {isAdmin ? (
                org?.githubConnected ? (
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="dash-ghost-button"
                      disabled={gh.busy}
                      onClick={() =>
                        gh.run(async () => {
                          const out = await projectApi.syncGithub(team.id)
                          setSyncNote(`${out.claims_created} untracked pull request${out.claims_created === 1 ? '' : 's'} added as claims.`)
                          await refresh()
                        })
                      }
                    >
                      {gh.busy ? <Busy label="Syncing…" /> : 'Sync open pull requests'}
                    </button>
                    <button type="button" className="dash-ghost-button" disabled={gh.busy} onClick={() => gh.run(disconnectGithub)}>
                      Disconnect
                    </button>
                  </div>
                ) : user?.github_login ? (
                  <button type="button" className="dash-primary-button" disabled={gh.busy} onClick={() => gh.run(connectGithub)}>
                    {gh.busy ? <Busy label="Connecting…" /> : (
                      <>
                        <Icon.GitHub size={16} />
                        Connect as {user.github_login}
                      </>
                    )}
                  </button>
                ) : (
                  <DashNotice tone="info">Sign in with GitHub to connect it. The connecting account's token is used for pull requests, so use the one that administers the repositories.</DashNotice>
                )
              ) : (
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-3)' }}>Only an admin can change this.</p>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Repository for {team.name}</h2>
                <p>{current.repo ?? 'No repository linked yet.'}</p>
              </div>
              <span className={`badge badge--${current.webhookId ? 'ok' : 'muted'}`}>{current.webhookId ? 'Webhook on' : 'No webhook'}</span>
            </div>
            <div className="panel__body">
              {hook.error && <DashNotice tone="danger">{hook.error}</DashNotice>}
              <WebhookLine status={hookStatus} />
              {isAdmin && (
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <Link to={`/app/settings?team=${team.id}`} className="dash-ghost-button">
                    Change repository
                  </Link>
                  {current.repo && (
                    <button
                      type="button"
                      className="dash-ghost-button"
                      disabled={hook.busy}
                      onClick={() =>
                        hook.run(async () => {
                          setHookStatus(await projectApi.registerWebhook(team.id))
                          await updateTeam(team.id, {})
                        })
                      }
                    >
                      {hook.busy ? <Busy label="Registering…" /> : 'Register merge webhook'}
                    </button>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Notion</h2>
                <p>{org?.notionConnected ? `Tasks sync from database ${org.notionTasksDbId ?? ''}; decisions and rulings mirror out as pages.` : 'Paste an internal integration token and the id of the tasks database.'}</p>
              </div>
              <span className={`badge badge--${org?.notionConnected ? 'ok' : 'muted'}`}>{org?.notionConnected ? 'Connected' : 'Off'}</span>
            </div>
            <div className="panel__body">
              {notion.error && <DashNotice tone="danger">{notion.error}</DashNotice>}
              {!isAdmin ? (
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-3)' }}>Only an admin can change this.</p>
              ) : org?.notionConnected ? (
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <Link to={`/app/tasks?team=${team.id}`} className="dash-ghost-button">
                    Sync tasks
                  </Link>
                  <button type="button" className="dash-ghost-button" disabled={notion.busy} onClick={() => notion.run(disconnectNotion)}>
                    Disconnect
                  </button>
                </div>
              ) : (
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    void notion.run(async () => {
                      await connectNotion(notionForm)
                      setNotionForm({ token: '', databaseId: '' })
                    })
                  }}
                >
                  <label className="dash-field">
                    <span className="dash-field__label">Internal integration token</span>
                    <input className="dash-input mono" type="password" placeholder="ntn_…" value={notionForm.token} onChange={(event) => setNotionForm({ ...notionForm, token: event.target.value })} />
                  </label>
                  <label className="dash-field">
                    <span className="dash-field__label">Tasks database id</span>
                    <input className="dash-input mono" placeholder="32 hex characters" value={notionForm.databaseId} onChange={(event) => setNotionForm({ ...notionForm, databaseId: event.target.value })} />
                  </label>
                  <button type="submit" className="dash-primary-button btn-block" disabled={notion.busy || !notionForm.token.trim() || !notionForm.databaseId.trim()}>
                    {notion.busy ? <Busy label="Connecting…" /> : 'Connect Notion'}
                  </button>
                </form>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>MCP</h2>
                <p>How agents talk to Consensus. Keys live in Settings.</p>
              </div>
            </div>
            <div className="panel__body">
              <CopyRow label="Server URL" value={`${window.location.origin}/mcp`} />
              <Link to={`/app/settings?team=${team.id}`} className="dash-quiet-button">
                Create an API key
                <Icon.ArrowRight size={15} />
              </Link>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------
   Settings
   ------------------------------------------------------------------- */

function RepoField({ value, onChange, connected, repos }: { value: string; onChange: (v: string) => void; connected: boolean; repos: GithubRepo[] | null }) {
  const listed = repos?.some((r) => r.full_name === value)
  return (
    <label className="dash-field">
      <span className="dash-field__label">Repository</span>
      {connected && repos && repos.length > 0 ? (
        <select className="dash-select" value={listed || value === '' ? value : '__custom'} onChange={(event) => onChange(event.target.value === '__custom' ? value : event.target.value)}>
          <option value="">No repository</option>
          {repos.map((repo) => (
            <option key={repo.full_name} value={repo.full_name}>
              {repo.full_name}
              {repo.private ? ' (private)' : ''}
            </option>
          ))}
          {!listed && value && <option value="__custom">{value}</option>}
        </select>
      ) : (
        <input className="dash-input mono" placeholder="owner/repository" value={value} onChange={(event) => onChange(event.target.value)} />
      )}
      <p className="dash-field__hint">{connected ? 'Repositories the connected GitHub account can see.' : 'Connect GitHub in Integrations to pick from a list instead of typing.'}</p>
    </label>
  )
}

function useRepos(enabled: boolean) {
  const { githubRepos } = useSession()
  const [repos, setRepos] = useState<GithubRepo[] | null>(null)
  useEffect(() => {
    if (!enabled) return
    githubRepos().then(setRepos).catch(() => setRepos(null))
  }, [enabled, githubRepos])
  return repos
}

function SettingsPage() {
  const { team, counters } = useProject()
  const { org, user, isAdmin, teamById, updateTeam, updateOrg, listKeys, createKey, revokeKey } = useSession()
  const current = teamById(team.id) ?? team

  const [keys, setKeys] = useState<ApiKey[]>([])
  const [keyName, setKeyName] = useState('')
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const keyAction = useAction()

  const [teamName, setTeamName] = useState(current.name)
  const [repo, setRepo] = useState(current.repo ?? '')
  const [teamResult, setTeamResult] = useState<Project | null>(null)
  const teamAction = useAction()
  const repos = useRepos(Boolean(org?.githubConnected && isAdmin))

  const [orgName, setOrgName] = useState(org?.name ?? '')
  const [domain, setDomain] = useState(org?.domain ?? '')
  const orgAction = useAction()
  const [orgSaved, setOrgSaved] = useState(false)

  useEffect(() => {
    listKeys().then(setKeys).catch(() => setKeys([]))
  }, [listKeys])

  const teamKeys = keys.filter((k) => !k.revoked_at && (k.project_id === team.id || k.project_id === null))
  const mcpCommand = created ? `claude mcp add --transport http consensus ${created.mcp_url} --header "Authorization: Bearer ${created.key}"` : ''

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Settings</h1>
          <p>Connect agents, and manage {team.name} and {org?.name}.</p>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>API keys</h2>
                <p>An agent presents a key to the MCP server. Everything it does is attributed to you.</p>
              </div>
            </div>
            <div className="panel__body">
              {created ? (
                <>
                  <DashNotice tone="warn">This key is shown once. Copy it now; it cannot be recovered later.</DashNotice>
                  <CopyRow label="API key" value={created.key} />
                  <CopyRow label="MCP server URL" value={created.mcp_url} />
                  <CopyRow label="Add to Claude Code" value={mcpCommand} hint="Or install the plugin: claude plugin marketplace add masterblaster14/Consensus, then claude plugin install consensus@consensus with CONSENSUS_API_KEY set." />
                  <button type="button" className="dash-ghost-button" onClick={() => setCreated(null)}>
                    Done
                  </button>
                </>
              ) : (
                <form
                  style={{ display: 'flex', gap: 10, alignItems: 'end', flexWrap: 'wrap' }}
                  onSubmit={(event) => {
                    event.preventDefault()
                    void keyAction.run(async () => {
                      const out = await createKey({ name: keyName.trim() || undefined, projectId: team.id })
                      setCreated(out)
                      setKeyName('')
                      setKeys(await listKeys())
                    })
                  }}
                >
                  <label className="dash-field" style={{ flex: 1, marginBottom: 0 }}>
                    <span className="dash-field__label">Key name</span>
                    <input className="dash-input" placeholder={`${firstName(user?.name ?? '')}'s laptop`} value={keyName} onChange={(event) => setKeyName(event.target.value)} />
                  </label>
                  <button type="submit" className="dash-primary-button" disabled={keyAction.busy}>
                    {keyAction.busy ? <Busy label="Creating…" /> : (
                      <>
                        <Icon.Key size={15} />
                        Create key for {team.name}
                      </>
                    )}
                  </button>
                </form>
              )}
              {keyAction.error && <DashNotice tone="danger">{keyAction.error}</DashNotice>}

              <div style={{ marginTop: 18 }}>
                {teamKeys.length === 0 ? (
                  <p style={{ fontSize: '0.8125rem', color: 'var(--text-3)' }}>You have no active keys for this team yet.</p>
                ) : (
                  teamKeys.map((key) => (
                    <div className="mem-item" key={key.id} style={{ padding: '10px 0' }}>
                      <div className="mem-item__top">
                        <span className="mono">{key.prefix}…</span>
                        <span className="mem-item__concepts">{key.name}</span>
                        <span className="badge">{key.last_used_at ? `used ${relative(key.last_used_at)}` : 'never used'}</span>
                        <button
                          type="button"
                          className="dash-quiet-button"
                          onClick={() =>
                            keyAction.run(async () => {
                              await revokeKey(key.id)
                              setKeys(await listKeys())
                            })
                          }
                        >
                          Revoke
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <div>
                <h2>Account</h2>
                <p>{user?.email}</p>
              </div>
            </div>
            <div className="panel__body">
              <dl className="kv">
                <dt>Name</dt>
                <dd>{user?.name}</dd>
                <dt>GitHub</dt>
                <dd>{user?.github_login ?? 'not linked'}</dd>
                <dt>Role in {org?.name}</dt>
                <dd>{isAdmin ? 'Admin' : 'Member'}</dd>
                <dt>Conflicts caught here</dt>
                <dd>{counters?.clashes_caught ?? 0}</dd>
                <dt>Tokens saved by memory</dt>
                <dd>{(counters?.tokens_saved ?? 0).toLocaleString()}</dd>
              </dl>
            </div>
          </section>
        </div>

        <div className="stack">
          {isAdmin && (
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Team</h2>
                  <p>Rename {team.name} or change the repository it tracks.</p>
                </div>
              </div>
              <form
                className="panel__body"
                onSubmit={(event) => {
                  event.preventDefault()
                  void teamAction.run(async () => {
                    const out = await updateTeam(team.id, { name: teamName.trim() || undefined, repo: repo.trim() })
                    setTeamResult(out)
                  })
                }}
              >
                <label className="dash-field">
                  <span className="dash-field__label">Team name</span>
                  <input className="dash-input" value={teamName} onChange={(event) => setTeamName(event.target.value)} />
                </label>
                <RepoField value={repo} onChange={setRepo} connected={Boolean(org?.githubConnected)} repos={repos} />
                {teamAction.error && <DashNotice tone="danger">{teamAction.error}</DashNotice>}
                {teamResult && <WebhookLine status={teamResult.webhook} />}
                {teamResult && !teamResult.webhook && <DashNotice tone="success">Saved.</DashNotice>}
                <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', flexWrap: 'wrap' }}>
                  <Link to={`/app/teams/delete?target=${team.id}`} className="dash-ghost-button">
                    <Icon.Trash />
                    Archive team
                  </Link>
                  <button type="submit" className="dash-primary-button" disabled={teamAction.busy}>
                    {teamAction.busy ? <Busy label="Saving…" /> : 'Save team'}
                  </button>
                </div>
              </form>
            </section>
          )}

          {isAdmin && (
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Organisation</h2>
                  <p>Name and the email domain that joins automatically.</p>
                </div>
              </div>
              <form
                className="panel__body"
                onSubmit={(event) => {
                  event.preventDefault()
                  void orgAction.run(async () => {
                    await updateOrg({ name: orgName.trim() || undefined, domain: domain.trim() || null })
                    setOrgSaved(true)
                  })
                }}
              >
                <label className="dash-field">
                  <span className="dash-field__label">Organisation name</span>
                  <input className="dash-input" value={orgName} onChange={(event) => setOrgName(event.target.value)} />
                </label>
                <label className="dash-field">
                  <span className="dash-field__label">Auto-join domain</span>
                  <input className="dash-input" placeholder="acme.com" value={domain} onChange={(event) => setDomain(event.target.value)} />
                  <p className="dash-field__hint">Anyone who signs in with a verified email at this domain joins as a member. Leave empty to require invites.</p>
                </label>
                {orgAction.error && <DashNotice tone="danger">{orgAction.error}</DashNotice>}
                {orgSaved && !orgAction.error && <DashNotice tone="success">Saved.</DashNotice>}
                <button type="submit" className="dash-primary-button btn-block" disabled={orgAction.busy}>
                  {orgAction.busy ? <Busy label="Saving…" /> : 'Save organisation'}
                </button>
              </form>
            </section>
          )}

          {!isAdmin && (
            <section className="panel">
              <div className="panel__head">
                <div>
                  <h2>Team</h2>
                  <p>{team.name} tracks {current.repo ?? 'no repository'}. Admins manage teams and members.</p>
                </div>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------
   Teams: everyone sees this; admins see every team plus the actions
   ------------------------------------------------------------------- */

function TeamsPage() {
  const { isAdmin, org, teams, people } = useSession()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Record<string, Counters>>({})

  useEffect(() => {
    let cancelled = false
    Promise.all(teams.map((t) => projectApi.counters(t.id).then((c) => [t.id, c] as const).catch(() => null))).then((rows) => {
      if (cancelled) return
      const next: Record<string, Counters> = {}
      for (const row of rows) if (row) next[row[0]] = row[1]
      setStats(next)
    })
    return () => {
      cancelled = true
    }
  }, [teams])

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Teams</h1>
          <p>
            {teams.length} team{teams.length === 1 ? '' : 's'} in {org?.name}. A team maps to one repository and one shared memory, visible to every member.
          </p>
        </div>
        {isAdmin && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Link to="/app/teams/domain" className="dash-ghost-button">
              <Icon.Globe />
              Auto-join domain
            </Link>
            <Link to="/app/teams/create" className="dash-primary-button">
              <Icon.Plus />
              Create team
            </Link>
          </div>
        )}
      </div>

      {teams.length === 0 ? (
        <EmptyPanel
          title="No teams yet"
          body={isAdmin ? 'Create one, then issue an API key so agents can join it.' : 'An admin needs to create the first team.'}
          action={
            isAdmin ? (
              <Link to="/app/teams/create" className="dash-primary-button">
                <Icon.Plus />
                Create your first team
              </Link>
            ) : undefined
          }
        />
      ) : (
        <div className="team-grid">
          {teams.map((team) => {
            const c = stats[team.id]
            return (
              <article className="team-card" key={team.id}>
                <div className="team-card__top">
                  <span className="team-card__mark">{initials(team.name)}</span>
                  <div style={{ minWidth: 0 }}>
                    <h3>{team.name}</h3>
                    <div className="team-card__repo">{team.repo ?? 'No repository linked'}</div>
                  </div>
                </div>
                <div className="team-card__meta">
                  <div>
                    <b>{people.length}</b>
                    <span>members</span>
                  </div>
                  <div>
                    <b>{c?.agents ?? '…'}</b>
                    <span>agents</span>
                  </div>
                  <div>
                    <b>{c?.open_clashes ?? '…'}</b>
                    <span>open conflicts</span>
                  </div>
                </div>
                {isAdmin && (
                  <div style={{ marginBottom: 14 }}>
                    {team.webhookId ? <span className="badge badge--ok">webhook on</span> : <span className="badge badge--muted">no webhook</span>}{' '}
                    {c ? <span className="chip">{c.memory_count} memories</span> : null}
                  </div>
                )}
                <div className="team-card__actions">
                  <Link to={`/app/dashboard?team=${team.id}`} className="dash-primary-button">
                    Open dashboard
                    <Icon.ArrowRight size={15} />
                  </Link>
                  {isAdmin && (
                    <button type="button" className="icon-btn icon-btn--danger" aria-label={`Archive ${team.name}`} onClick={() => navigate(`/app/teams/delete?target=${team.id}`)}>
                      <Icon.Trash />
                    </button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------
   Admin: manage teams
   ------------------------------------------------------------------- */

const CREATED_KEY = 'consensus.created-team'

function CreateTeamPage() {
  const { org, createTeam } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [name, setName] = useState('')
  const [repo, setRepo] = useState('')
  const { busy, error, setError, run } = useAction()
  const repos = useRepos(Boolean(org?.githubConnected))

  // The created project (with its webhook outcome) survives the remount that happens when the
  // admin's first team turns the empty shell into the real one.
  const created: Project | null = useMemo(() => {
    const id = params.get('created')
    if (!id) return null
    try {
      const raw = sessionStorage.getItem(CREATED_KEY)
      const parsed = raw ? (JSON.parse(raw) as Project) : null
      return parsed && parsed.id === id ? parsed : null
    } catch {
      return null
    }
  }, [params])

  if (created) {
    return (
      <AdminPage title="Team created" blurb={`${created.name} is ready. Every member of ${org?.name} can see it.`} back="/app/teams">
        {created.repo_full_name ? <WebhookLine status={created.webhook} /> : <DashNotice tone="info">No repository linked. Add one in Settings when you want handoffs to open pull requests.</DashNotice>}
        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
          <button
            type="button"
            className="dash-ghost-button"
            style={{ flex: 1 }}
            onClick={() => {
              setName('')
              setRepo('')
              navigate('/app/teams/create', { replace: true })
            }}
          >
            Create another
          </button>
          <Link to={`/app/settings?team=${created.id}`} className="dash-ghost-button" style={{ flex: 1 }}>
            Create an API key
          </Link>
          <Link to={`/app/dashboard?team=${created.id}`} className="dash-primary-button" style={{ flex: 1 }}>
            Open it
          </Link>
        </div>
      </AdminPage>
    )
  }

  return (
    <AdminPage title="Create a team" blurb="One team, one repository, one shared memory." back="/app/teams">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!name.trim()) {
            setError('Give the team a name.')
            return
          }
          void run(async () => {
            const project = await createTeam({ name, repo })
            try {
              sessionStorage.setItem(CREATED_KEY, JSON.stringify(project))
            } catch {
              /* ignore */
            }
            navigate(`/app/teams/create?created=${project.id}`, { replace: true })
          })
        }}
      >
        <label className="dash-field">
          <span className="dash-field__label">Team name</span>
          <input
            className={`dash-input${error ? ' is-invalid' : ''}`}
            placeholder="Checkout Platform"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              setError(null)
            }}
            autoFocus
          />
        </label>
        <RepoField value={repo} onChange={setRepo} connected={Boolean(org?.githubConnected)} repos={repos} />
        {error && <DashNotice tone="danger">{error}</DashNotice>}
        <button type="submit" className="dash-primary-button btn-block" disabled={busy}>
          {busy ? <Busy label="Creating…" /> : (
            <>
              <Icon.Plus />
              Create team
            </>
          )}
        </button>
      </form>
    </AdminPage>
  )
}

function DeleteTeamPage() {
  const { teams, archiveTeam } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [targetId, setTargetId] = useState(params.get('target') ?? '')
  const [confirmText, setConfirmText] = useState('')
  const { busy, error, run } = useAction()
  const team = teams.find((item) => item.id === targetId) ?? null

  return (
    <AdminPage title="Archive a team" blurb="The team disappears from every list and its agents can no longer declare against it. Its history stays readable and it can be restored." back="/app/teams">
      <label className="dash-field">
        <span className="dash-field__label">Team</span>
        <select
          className="dash-select"
          value={targetId}
          onChange={(event) => {
            setTargetId(event.target.value)
            setConfirmText('')
          }}
        >
          <option value="">Choose a team…</option>
          {teams.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>

      {team && (
        <>
          <div className="confirm-target">
            <div>
              <b>{team.name}</b>
              <span>{team.repo ?? 'No repository'}</span>
            </div>
          </div>
          <DashNotice tone="danger">
            Agents holding keys for <b>{team.name}</b> get "project is archived" on their next declaration.
          </DashNotice>
          <label className="dash-field">
            <span className="dash-field__label">
              Type <b>{team.name}</b> to confirm
            </span>
            <input className="dash-input" value={confirmText} onChange={(event) => setConfirmText(event.target.value)} placeholder={team.name} />
          </label>
          {error && <DashNotice tone="danger">{error}</DashNotice>}
          <button
            type="button"
            className="dash-danger-button btn-block"
            disabled={busy || confirmText !== team.name}
            onClick={() =>
              run(async () => {
                await archiveTeam(team.id)
                navigate('/app/teams')
              })
            }
          >
            {busy ? <Busy label="Archiving…" /> : (
              <>
                <Icon.Trash />
                Archive team
              </>
            )}
          </button>
        </>
      )}
    </AdminPage>
  )
}

function DomainPage() {
  const { org, updateOrg } = useSession()
  const navigate = useNavigate()
  const [domain, setDomain] = useState(org?.domain ?? '')
  const { busy, error, run } = useAction()

  return (
    <AdminPage title="Auto-join domain" blurb={`Anyone who signs in with a verified email at this domain joins ${org?.name} as a member, no invite needed.`} back="/app/teams">
      <label className="dash-field">
        <span className="dash-field__label">Current domain</span>
        <input className="dash-input" value={org?.domain ? `@${org.domain}` : 'Not set'} readOnly style={{ background: 'var(--surface-2)', color: 'var(--text-3)' }} />
      </label>
      <label className="dash-field">
        <span className="dash-field__label">New domain</span>
        <input className="dash-input" placeholder="acme.com" value={domain} onChange={(event) => setDomain(event.target.value)} />
        <p className="dash-field__hint">Leave empty to require invites for everyone.</p>
      </label>
      {error && <DashNotice tone="danger">{error}</DashNotice>}
      <button
        type="button"
        className="dash-primary-button btn-block"
        disabled={busy}
        onClick={() =>
          run(async () => {
            await updateOrg({ domain: domain.trim() || null })
            navigate('/app/teams')
          })
        }
      >
        {busy ? <Busy label="Saving…" /> : 'Save domain'}
      </button>
    </AdminPage>
  )
}

/* -------------------------------------------------------------------
   Admin: manage members
   ------------------------------------------------------------------- */

function MembersPage() {
  const { org, people, user, setRole, setRestricted } = useSession()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const { busy, error, run } = useAction()

  const filtered = people.filter((person) => {
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return `${person.name} ${person.email}`.toLowerCase().includes(needle)
  })

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Members</h1>
          <p>
            {people.length} {people.length === 1 ? 'person' : 'people'} in {org?.name}. Roles are organisation-wide, and every member sees every team.
          </p>
        </div>
        <Link to="/app/members/add" className="dash-primary-button">
          <Icon.UserPlus size={15} />
          Invite member
        </Link>
      </div>

      {error && <DashNotice tone="danger">{error}</DashNotice>}

      <section className="panel">
        <div className="panel__head">
          <div className="dash-search">
            <Icon.Search />
            <input className="dash-input" placeholder="Search name or email" value={query} onChange={(event) => setQuery(event.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to="/app/members/restrict" className="dash-ghost-button">
              <Icon.Lock />
              Restrict
            </Link>
            <Link to="/app/members/remove" className="dash-ghost-button">
              <Icon.Trash />
              Remove
            </Link>
          </div>
        </div>

        <div className="panel__body panel__body--flush table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((person) => (
                <tr key={person.id}>
                  <td>
                    <div className="user-cell">
                      <span className="dash-avatar">{initials(person.name)}</span>
                      <div>
                        <div className="cell-strong">
                          {person.name}
                          {person.id === user?.id ? ' (you)' : ''}
                        </div>
                        <div className="cell-sub">{person.email}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <select className="dash-select" style={{ height: 34, width: 116 }} value={person.role} disabled={busy} onChange={(event) => run(() => setRole(person.id, event.target.value as Role))}>
                      <option value="admin">Admin</option>
                      <option value="member">Member</option>
                    </select>
                  </td>
                  <td>
                    {person.restricted ? (
                      <span className="badge badge--warn">
                        <Icon.Lock size={11} />
                        Restricted
                      </span>
                    ) : (
                      <span className="badge badge--ok">
                        <span className="badge__dot" />
                        Active
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button type="button" className="dash-quiet-button" disabled={busy} onClick={() => run(() => setRestricted(person.id, !person.restricted))}>
                        {person.restricted ? 'Unrestrict' : 'Restrict'}
                      </button>
                      <button type="button" className="icon-btn icon-btn--danger" aria-label={`Remove ${person.name}`} onClick={() => navigate(`/app/members/remove?target=${person.id}`)}>
                        <Icon.Trash />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="empty-state">
              <Icon.Inbox />
              <b>No one matches "{query}"</b>
              <p>Try a different name or email.</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function AddMemberPage() {
  const { org, invite } = useSession()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [invited, setInvited] = useState<Invite | null>(null)
  const { busy, error, setError, run } = useAction()

  if (invited) {
    return (
      <AdminPage
        title="Invite ready"
        blurb={invited.email_sent ? `We emailed the link to ${invited.email}. You can also send it yourself.` : invited.email ? `Send this link to ${invited.email}.` : 'Anyone with this link can join. It works once.'}
        back="/app/members"
      >
        <CopyRow label="Invite link" value={invited.url ?? ''} hint={`Joins ${org?.name} as ${invited.role === 'admin' ? 'an admin' : 'a member'}. Expires ${invited.expires_at ? new Date(invited.expires_at).toLocaleDateString() : 'in 7 days'}.`} />
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className="dash-ghost-button"
            style={{ flex: 1 }}
            onClick={() => {
              setInvited(null)
              setEmail('')
            }}
          >
            Invite someone else
          </button>
          <Link to="/app/members" className="dash-primary-button" style={{ flex: 1 }}>
            Done
          </Link>
        </div>
      </AdminPage>
    )
  }

  return (
    <AdminPage title="Invite a member" blurb={`They sign in with GitHub, accept, and land in ${org?.name} with access to every team.`} back="/app/members">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
            setError('Enter a valid email address, or leave it empty for an open link.')
            return
          }
          void run(async () => setInvited(await invite({ email: email.trim() || undefined, role })))
        }}
      >
        <label className="dash-field">
          <span className="dash-field__label">Email address (optional)</span>
          <input
            className={`dash-input${error ? ' is-invalid' : ''}`}
            type="email"
            placeholder="teammate@acme.com"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value)
              setError(null)
            }}
            autoFocus
          />
          <p className="dash-field__hint">With an email the link only works for that address. Without one, anyone holding the link can join once.</p>
        </label>
        <label className="dash-field">
          <span className="dash-field__label">Role</span>
          <select className="dash-select" value={role} onChange={(event) => setRole(event.target.value as Role)}>
            <option value="member">Member: reads the board, arbitrates conflicts involving their agents</option>
            <option value="admin">Admin: also manages teams, members and integrations</option>
          </select>
        </label>
        {error && <DashNotice tone="danger">{error}</DashNotice>}
        <button type="submit" className="dash-primary-button btn-block" disabled={busy}>
          {busy ? <Busy label="Creating…" /> : (
            <>
              <Icon.UserPlus size={15} />
              Create invite
            </>
          )}
        </button>
      </form>
    </AdminPage>
  )
}

function PersonPicker({ people, value, onChange }: { people: Person[]; value: string; onChange: (id: string) => void }) {
  return (
    <label className="dash-field">
      <span className="dash-field__label">Member</span>
      <select className="dash-select" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose a member…</option>
        {people.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name} — {item.email}
          </option>
        ))}
      </select>
    </label>
  )
}

function RemoveMemberPage() {
  const { org, people, removeMember, user } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [targetId, setTargetId] = useState(params.get('target') ?? '')
  const { busy, error, run } = useAction()
  const person = people.find((item) => item.id === targetId) ?? null
  const isSelf = person?.id === user?.id

  return (
    <AdminPage title="Remove a member" blurb={`They lose access to ${org?.name}. Their claims, rulings and memory entries stay.`} back="/app/members">
      <PersonPicker people={people} value={targetId} onChange={setTargetId} />
      {person && (
        <>
          <div className="confirm-target">
            <div className="user-cell">
              <span className="dash-avatar">{initials(person.name)}</span>
              <div>
                <b>{person.name}</b>
                <span>{person.email}</span>
              </div>
            </div>
            <span className={`badge${person.role === 'admin' ? ' badge--admin' : ''}`}>{person.role === 'admin' ? 'Admin' : 'Member'}</span>
          </div>
          {isSelf && <DashNotice tone="danger">That's you. Removing your own account signs you out immediately.</DashNotice>}
          {!isSelf && person.role === 'admin' && <DashNotice tone="danger">{person.name} is an admin. The last active admin cannot be removed.</DashNotice>}
          {error && <DashNotice tone="danger">{error}</DashNotice>}
          <button
            type="button"
            className="dash-danger-button btn-block"
            disabled={busy}
            onClick={() =>
              run(async () => {
                await removeMember(person.id)
                navigate(isSelf ? '/' : '/app/members')
              })
            }
          >
            {busy ? <Busy label="Removing…" /> : (
              <>
                <Icon.UserMinus size={15} />
                Remove {person.name}
              </>
            )}
          </button>
        </>
      )}
    </AdminPage>
  )
}

function RestrictMemberPage() {
  const { people, setRestricted } = useSession()
  const [targetId, setTargetId] = useState('')
  const { busy, error, run } = useAction()
  const person = people.find((item) => item.id === targetId) ?? null

  return (
    <AdminPage title="Restrict a member" blurb="A restricted member reads everything but cannot declare, write memory, rule on conflicts or manage anything until reinstated." back="/app/members">
      <PersonPicker people={people} value={targetId} onChange={setTargetId} />
      {person && (
        <>
          <div className="confirm-target">
            <div className="user-cell">
              <span className="dash-avatar">{initials(person.name)}</span>
              <div>
                <b>{person.name}</b>
                <span>{person.email}</span>
              </div>
            </div>
            <span className={`badge badge--${person.restricted ? 'warn' : 'ok'}`}>{person.restricted ? 'Restricted' : 'Active'}</span>
          </div>
          {error && <DashNotice tone="danger">{error}</DashNotice>}
          <label className="dash-switch" style={{ marginBottom: 20 }}>
            <input type="checkbox" checked={person.restricted} disabled={busy} onChange={(event) => run(() => setRestricted(person.id, event.target.checked))} />
            <span className="dash-switch__track" />
            <span style={{ fontSize: '0.875rem' }}>Restrict {firstName(person.name)} to read-only</span>
          </label>
          <Link to="/app/members" className="dash-primary-button btn-block">
            Done
          </Link>
        </>
      )}
    </AdminPage>
  )
}
