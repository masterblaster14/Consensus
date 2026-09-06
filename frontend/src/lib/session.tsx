import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import {
  ApiError,
  auth,
  authApi,
  inviteApi,
  keyApi,
  orgApi,
  projectApi,
  type ApiKey,
  type ApiKeyCreated,
  type AuthProviders,
  type GithubRepo,
  type Invite,
  type Me,
  type Membership,
  type MemberStatus,
  type Org,
  type Project,
  type Role,
  type User,
} from './api'

/**
 * Real session + organisation store.
 *
 * Who is signed in (a JWT in localStorage, exchanged for /api/auth/me), which
 * organisation is current, its teams (backend: projects), its members, and the
 * write operations the admin screens need. Everything on this object is backed
 * by a backend call; nothing is held only in the browser except the choice of
 * current organisation.
 */

export type { Role }

export interface Team {
  id: string
  name: string
  repo: string | null
  createdAt: string | null
  archivedAt: string | null
  webhookId: number | null
}

export interface Person {
  /** The user id: what member endpoints are addressed by. */
  id: string
  name: string
  email: string
  role: Role
  restricted: boolean
  avatarUrl: string | null
}

export interface OrgView {
  id: string
  name: string
  slug: string
  domain: string | null
  githubConnected: boolean
  githubConnectedBy: string | null
  notionConnected: boolean
  notionTasksDbId: string | null
}

const ORG_KEY = 'consensus.org'

const toTeam = (p: Project): Team => ({
  id: p.id,
  name: p.name,
  repo: p.repo_full_name,
  createdAt: p.created_at,
  archivedAt: p.archived_at,
  webhookId: p.webhook_id,
})

const toPerson = (m: Membership): Person => ({
  id: m.user_id,
  name: m.user_name || m.user_email || 'Member',
  email: m.user_email ?? '',
  role: m.role,
  restricted: m.status === 'restricted',
  avatarUrl: m.user_avatar_url,
})

const toOrgView = (o: Org): OrgView => ({
  id: o.id,
  name: o.name,
  slug: o.slug,
  domain: o.auto_join_domain,
  githubConnected: Boolean(o.integrations?.github?.connected),
  githubConnectedBy: o.integrations?.github?.connected_by ?? null,
  notionConnected: Boolean(o.integrations?.notion?.connected),
  notionTasksDbId: o.integrations?.notion?.tasks_db_id ?? null,
})

export function initials(name: string) {
  return (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

export function firstName(name: string) {
  return (name || 'there').split(/\s+/)[0]!
}

/** Human message for an API failure. */
export function describeError(problem: unknown, fallback = 'Something went wrong.') {
  if (problem instanceof ApiError) {
    if (problem.status === 0) return problem.detail
    if (problem.status === 401) return 'Your session has expired. Sign in again.'
    return problem.detail || fallback
  }
  if (problem instanceof Error && problem.message) return problem.message
  return fallback
}

/** Pull an invite token out of a pasted link or a bare token. */
export function inviteTokenFrom(input: string): string | null {
  const text = input.trim()
  if (!text) return null
  const match = text.match(/invite\/([A-Za-z0-9_-]{8,})/)
  if (match) return match[1]!
  return /^[A-Za-z0-9_-]{8,}$/.test(text) ? text : null
}

/* -------------------------------------------------------------------
   Context
   ------------------------------------------------------------------- */

type Status = 'loading' | 'anonymous' | 'ready'

interface SessionValue {
  status: Status
  user: User | null
  memberships: Membership[]
  providers: AuthProviders | null

  /** Current organisation, or null when the account belongs to none yet. */
  org: OrgView | null
  orgs: OrgView[]
  isAdmin: boolean
  isRestricted: boolean
  /** Every org member sees every team in the organisation. */
  teams: Team[]
  people: Person[]
  loadError: string | null

  // sign-in
  startGithub: (next: string) => Promise<void>
  completeToken: (token: string) => Promise<Me>
  devLogin: (email: string, name?: string) => Promise<Me>
  requestMagicLink: (email: string, name?: string) => Promise<{ sent: boolean; devLink?: string }>
  verifyMagic: (token: string) => Promise<Me>
  signOut: () => void
  refresh: () => Promise<void>

  // organisations
  createOrg: (input: { name: string; domain: string }) => Promise<OrgView>
  acceptInvite: (token: string) => Promise<OrgView>
  previewInvite: (token: string) => Promise<Invite>
  switchOrg: (orgId: string) => void
  updateOrg: (input: { name?: string; domain?: string | null }) => Promise<void>

  // teams (projects)
  createTeam: (input: { name: string; repo?: string }) => Promise<Project>
  updateTeam: (teamId: string, input: { name?: string; repo?: string | null }) => Promise<Project>
  archiveTeam: (teamId: string) => Promise<void>
  teamById: (teamId: string) => Team | undefined

  // members
  invite: (input: { email?: string; role: Role }) => Promise<Invite>
  removeMember: (userId: string) => Promise<void>
  setRole: (userId: string, role: Role) => Promise<void>
  setRestricted: (userId: string, restricted: boolean) => Promise<void>

  // integrations
  connectGithub: () => Promise<void>
  disconnectGithub: () => Promise<void>
  githubRepos: () => Promise<GithubRepo[]>
  connectNotion: (input: { token: string; databaseId: string }) => Promise<void>
  disconnectNotion: () => Promise<void>

  // keys
  listKeys: () => Promise<ApiKey[]>
  createKey: (input: { name?: string; projectId?: string }) => Promise<ApiKeyCreated>
  revokeKey: (keyId: string) => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

function readOrgChoice(): string | null {
  try {
    return localStorage.getItem(ORG_KEY)
  } catch {
    return null
  }
}

function writeOrgChoice(orgId: string | null) {
  try {
    if (orgId) localStorage.setItem(ORG_KEY, orgId)
    else localStorage.removeItem(ORG_KEY)
  } catch {
    /* ignore */
  }
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>(auth.get() ? 'loading' : 'anonymous')
  const [me, setMe] = useState<Me | null>(null)
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [orgs, setOrgs] = useState<Org[]>([])
  const [orgId, setOrgId] = useState<string | null>(readOrgChoice)
  const [projects, setProjects] = useState<Project[]>([])
  const [members, setMembers] = useState<Membership[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const loadSeq = useRef(0)

  useEffect(() => {
    authApi.providers().then(setProviders).catch(() => setProviders({ github: false, magic_link: false, dev_login: false }))
  }, [])

  /** Load /me and the org list; pick the current org. */
  const loadAccount = useCallback(async (): Promise<Me | null> => {
    const seq = ++loadSeq.current
    if (!auth.get()) {
      setMe(null)
      setOrgs([])
      setStatus('anonymous')
      return null
    }
    try {
      const [account, orgList] = await Promise.all([authApi.me(), orgApi.list()])
      if (seq !== loadSeq.current) return account
      setMe(account)
      setOrgs(orgList)
      setLoadError(null)
      setOrgId((current) => {
        const wanted = current ?? readOrgChoice()
        const pick = orgList.find((o) => o.id === wanted)?.id ?? orgList[0]?.id ?? null
        writeOrgChoice(pick)
        return pick
      })
      setStatus('ready')
      return account
    } catch (problem) {
      if (problem instanceof ApiError && problem.status === 401) {
        auth.clear()
        setMe(null)
        setOrgs([])
        setStatus('anonymous')
        return null
      }
      setLoadError(describeError(problem))
      setStatus(auth.get() ? 'ready' : 'anonymous')
      return null
    }
  }, [])

  useEffect(() => {
    void loadAccount()
  }, [loadAccount])

  /** Teams and members follow the current org. */
  const loadOrgData = useCallback(async (id: string | null) => {
    if (!id) {
      setProjects([])
      setMembers([])
      return
    }
    try {
      const [projectList, memberList] = await Promise.all([orgApi.projects(id), orgApi.members(id)])
      setProjects(projectList)
      setMembers(memberList)
    } catch (problem) {
      setLoadError(describeError(problem))
    }
  }, [])

  useEffect(() => {
    if (status === 'ready') void loadOrgData(orgId)
  }, [status, orgId, loadOrgData])

  const refresh = useCallback(async () => {
    await loadAccount()
    await loadOrgData(orgId)
  }, [loadAccount, loadOrgData, orgId])

  const currentOrg = useMemo(() => orgs.find((o) => o.id === orgId) ?? null, [orgs, orgId])
  const membership = useMemo(() => me?.memberships.find((m) => m.org_id === orgId) ?? null, [me, orgId])

  const requireOrg = () => {
    if (!currentOrg) throw new Error('No organisation selected.')
    return currentOrg.id
  }

  const afterOrgChange = async (newOrg: Org) => {
    setOrgId(newOrg.id)
    writeOrgChoice(newOrg.id)
    await loadAccount()
    await loadOrgData(newOrg.id)
    return toOrgView(newOrg)
  }

  const value: SessionValue = {
    status,
    user: me?.user ?? null,
    memberships: me?.memberships ?? [],
    providers,
    org: currentOrg ? toOrgView(currentOrg) : null,
    orgs: orgs.map(toOrgView),
    isAdmin: membership?.role === 'admin' && membership.status === 'active',
    isRestricted: membership?.status === 'restricted',
    teams: projects.filter((p) => !p.archived_at).map(toTeam),
    people: members.map(toPerson),
    loadError,

    async startGithub(next) {
      const { url } = await authApi.githubStart(next)
      window.location.assign(url)
      await new Promise(() => {}) // the page is navigating away
    },
    async completeToken(token) {
      auth.set(token)
      setStatus('loading')
      const account = await loadAccount()
      if (!account) throw new Error('Sign-in did not complete.')
      return account
    },
    async devLogin(email, name) {
      const out = await authApi.devLogin(email, name)
      return value.completeToken(out.token)
    },
    async requestMagicLink(email, name) {
      const out = await authApi.magicLink(email, name)
      return { sent: out.sent, devLink: out.dev_link }
    },
    async verifyMagic(token) {
      const out = await authApi.magicVerify(token)
      return value.completeToken(out.token)
    },
    signOut() {
      auth.clear()
      writeOrgChoice(null)
      loadSeq.current += 1
      setMe(null)
      setOrgs([])
      setOrgId(null)
      setProjects([])
      setMembers([])
      setStatus('anonymous')
    },
    refresh,

    async createOrg({ name, domain }) {
      const created = await orgApi.create({ name: name.trim(), auto_join_domain: domain.trim() || undefined })
      return afterOrgChange(created)
    },
    async acceptInvite(token) {
      const joined = await inviteApi.accept(token)
      return afterOrgChange(joined)
    },
    previewInvite: (token) => inviteApi.preview(token),
    switchOrg(id) {
      setOrgId(id)
      writeOrgChoice(id)
    },
    async updateOrg({ name, domain }) {
      const id = requireOrg()
      const updated = await orgApi.update(id, { name, auto_join_domain: domain === undefined ? undefined : domain })
      setOrgs((current) => current.map((o) => (o.id === id ? updated : o)))
    },

    async createTeam({ name, repo }) {
      const id = requireOrg()
      const created = await orgApi.createProject(id, { name: name.trim(), repo_full_name: repo?.trim() || undefined })
      setProjects((current) => [...current, created])
      return created
    },
    async updateTeam(teamId, { name, repo }) {
      const updated = await projectApi.update(teamId, { name, repo_full_name: repo === undefined ? undefined : repo ?? '' })
      setProjects((current) => current.map((p) => (p.id === teamId ? updated : p)))
      return updated
    },
    async archiveTeam(teamId) {
      const id = requireOrg()
      await orgApi.archiveProject(id, teamId)
      setProjects((current) => current.filter((p) => p.id !== teamId))
    },
    teamById: (teamId) => projects.filter((p) => !p.archived_at).map(toTeam).find((t) => t.id === teamId),

    async invite({ email, role }) {
      const id = requireOrg()
      return orgApi.createInvite(id, { email: email?.trim() || undefined, role })
    },
    async removeMember(userId) {
      const id = requireOrg()
      await orgApi.removeMember(id, userId)
      if (userId === me?.user.id) {
        value.signOut()
        return
      }
      setMembers((current) => current.filter((m) => m.user_id !== userId))
    },
    async setRole(userId, role) {
      const id = requireOrg()
      const updated = await orgApi.updateMember(id, userId, { role })
      setMembers((current) => current.map((m) => (m.user_id === userId ? { ...m, ...updated } : m)))
      if (userId === me?.user.id) await loadAccount()
    },
    async setRestricted(userId, restricted) {
      const id = requireOrg()
      const statusValue: MemberStatus = restricted ? 'restricted' : 'active'
      const updated = await orgApi.updateMember(id, userId, { status: statusValue })
      setMembers((current) => current.map((m) => (m.user_id === userId ? { ...m, ...updated } : m)))
      if (userId === me?.user.id) await loadAccount()
    },

    async connectGithub() {
      const id = requireOrg()
      const updated = await orgApi.github.connect(id)
      setOrgs((current) => current.map((o) => (o.id === id ? updated : o)))
      await loadOrgData(id)
    },
    async disconnectGithub() {
      const id = requireOrg()
      const updated = await orgApi.github.disconnect(id)
      setOrgs((current) => current.map((o) => (o.id === id ? updated : o)))
    },
    githubRepos: () => orgApi.github.repos(requireOrg()),
    async connectNotion({ token, databaseId }) {
      const id = requireOrg()
      const updated = await orgApi.notion.connect(id, { notion_token: token.trim(), notion_tasks_db_id: databaseId.trim() })
      setOrgs((current) => current.map((o) => (o.id === id ? updated : o)))
    },
    async disconnectNotion() {
      const id = requireOrg()
      const updated = await orgApi.notion.disconnect(id)
      setOrgs((current) => current.map((o) => (o.id === id ? updated : o)))
    },

    listKeys: () => keyApi.list(),
    createKey: ({ name, projectId }) => keyApi.create({ name, org_id: requireOrg(), project_id: projectId }),
    revokeKey: (keyId) => keyApi.revoke(keyId),
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession must be used inside SessionProvider')
  return value
}

/* -------------------------------------------------------------------
   Route guards
   ------------------------------------------------------------------- */

export function LoadingScreen({ label = 'Loading your workspace…' }: { label?: string }) {
  return (
    <div className="session-loading" role="status" aria-live="polite">
      <span className="session-loading__dot" />
      {label}
    </div>
  )
}

/** The dashboard needs a signed-in account that belongs to an organisation. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, org } = useSession()
  const location = useLocation()

  if (status === 'loading') return <LoadingScreen />
  if (status === 'anonymous') {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/signin?next=${next}`} replace />
  }
  if (!org) return <Navigate to="/onboarding" replace />
  return <>{children}</>
}

/** Wraps the admin-only management screens. */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useSession()
  if (!isAdmin) return <Navigate to="/app/dashboard" replace />
  return <>{children}</>
}
