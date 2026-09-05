/**
 * Typed client for the Consensus backend.
 *
 * Source of truth: docs/backend-reference.md and app/schemas.py in this repo.
 * Nothing in the UI calls this yet; every screen still renders mock data.
 * Wire a screen by replacing its local state with the matching call below.
 *
 * Auth: every request carries `Authorization: Bearer <jwt>`. The JWT comes from
 * GitHub OAuth (callback lands on /auth/callback#token=...), a magic link, or
 * dev-login when the backend runs with DEV_AUTH=true.
 */

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
const TOKEN_KEY = 'consensus.token'

export const auth = {
  get token(): string | null {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(token: string) { try { localStorage.setItem(TOKEN_KEY, token) } catch { /* private mode */ } },
  clear() { try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } },
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown) {
    super(`API ${status}`)
    this.status = status
    this.body = body
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = auth.token
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b)
const patch = <T>(p: string, b?: unknown) => request<T>('PATCH', p, b)
const put = <T>(p: string, b?: unknown) => request<T>('PUT', p, b)
const del = <T>(p: string) => request<T>('DELETE', p)

const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

/* ── Types (mirror app/schemas.py) ─────────────────────────────────────── */

export type UUID = string
export type Role = 'admin' | 'member'
export type Verdict = 'proceed' | 'proceed_with_context' | 'wait'
export type ClaimStatus = 'open' | 'in_review' | 'retired'
export type ClashStatus = 'open' | 'resolved' | 'auto_resolved'
export type Severity = 'hard' | 'soft' | 'context' | 'clear'
export type Resolution = 'a_proceeds' | 'b_proceeds' | 'both_with_note'
export type MemoryType = 'discovery' | 'decision' | 'dead_end' | 'ruling' | 'handoff'

export interface User { id: UUID; email: string; name: string; avatar_url?: string | null; github_login?: string | null; created_at?: string | null }
export interface Membership { org_id: UUID; org_name?: string | null; org_slug?: string | null; role: Role; user_id: UUID; user_email?: string | null; user_name?: string | null; user_avatar_url?: string | null }
export interface Me { user: User; memberships: Membership[] }
export interface TokenOut { token: string; token_type: string; me: Me }
export interface Providers { github: boolean; magic_link: boolean; dev_login: boolean }

export interface Org {
  id: UUID; name: string; slug: string; auto_join_domain?: string | null; created_at?: string | null
  role?: Role | null
  integrations?: { github?: { connected: boolean; connected_by?: string | null }; notion?: { connected: boolean; tasks_db_id?: string | null } } | null
}
export interface Invite { id: UUID; org_id: UUID; org_name?: string | null; email?: string | null; role: Role; token?: string | null; url?: string | null; expires_at?: string | null; accepted_at?: string | null }
export interface InvitePreview { org_name: string; role: Role; email?: string | null }

export interface Project { id: UUID; org_id?: UUID | null; name: string; repo_full_name?: string | null; created_at?: string | null }
export interface Agent { id: UUID; project_id: UUID; name: string; developer_name: string; user_id?: UUID | null; last_seen?: string | null }
export interface Task { id: UUID; project_id: UUID; external_ref?: string | null; notion_page_id?: string | null; title: string }
export interface Stance { concepts: string[]; error_handling?: string | null; auth_check?: string | null; data_access?: string | null; api_shape?: string | null; summary: string }
export interface Claim {
  id: UUID; project_id: UUID; agent_id: UUID; agent_name?: string | null; developer_name?: string | null
  task_id?: UUID | null; task_ref?: string | null; intent_text: string; stance: Stance; concepts: string[]
  branch?: string | null; pr_number?: number | null; status: ClaimStatus; created_at?: string | null; resolved_at?: string | null
}
export interface MemoryEntry { id: UUID; project_id: UUID; type: MemoryType; content: string; concepts: string[]; axis?: string | null; source_agent_id?: UUID | null; source_agent?: string | null; related_claim_id?: UUID | null; created_at?: string | null }
export interface Clash {
  id: UUID; project_id: UUID; claim_a_id: UUID; claim_b_id: UUID
  agent_a?: string | null; agent_b?: string | null; intent_a?: string | null; intent_b?: string | null
  position_a?: string | null; position_b?: string | null; axis: string; shared_concepts: string[]
  severity: Severity; status: ClashStatus; resolution?: Resolution | null; resolution_note?: string | null; resolved_by?: string | null; created_at?: string | null
}
export interface Counters { tokens_saved: number; clashes_caught: number; memory_count: number; open_claims: number; open_clashes: number; agents: number }
export interface ContextItem { type: string; content: string; source?: string | null; entry_id?: UUID | null; similarity?: number | null }
export interface ApiKey { id: UUID; name: string; prefix: string; org_id: UUID; project_id?: UUID | null; created_at?: string | null; last_used_at?: string | null; revoked_at?: string | null }
export interface ApiKeyCreated extends ApiKey { key: string; mcp_url: string }

/* ── Auth ───────────────────────────────────────────────────────────────── */

export const authApi = {
  providers: () => get<Providers>('/api/auth/providers'),
  /** Returns the GitHub URL to send the browser to. The callback redirects to FRONTEND_URL/auth/callback#token=<jwt>&next=... */
  githubStart: (redirectTo?: string) => get<{ url: string }>(`/api/auth/github/start${q({ redirect_to: redirectTo })}`),
  magicLink: (email: string, name?: string) => post<{ ok?: boolean; dev_link?: string; dev_token?: string }>('/api/auth/magic-link', { email, name }),
  magicVerify: (token: string) => post<TokenOut>('/api/auth/magic-link/verify', { token }),
  /** DEV_AUTH=true only. Seeded admin: demo@example.com */
  devLogin: (email: string, name?: string) => post<TokenOut>('/api/auth/dev-login', { email, name }),
  me: () => get<Me>('/api/auth/me'),
}

/* ── Organisations, members, invites ────────────────────────────────────── */

export const orgApi = {
  list: () => get<Org[]>('/api/orgs'),
  create: (body: { name: string; slug?: string; auto_join_domain?: string }) => post<Org>('/api/orgs', body),
  get: (orgId: UUID) => get<Org>(`/api/orgs/${orgId}`),
  update: (orgId: UUID, body: { name?: string; auto_join_domain?: string | null }) => patch<Org>(`/api/orgs/${orgId}`, body),
  members: (orgId: UUID) => get<Membership[]>(`/api/orgs/${orgId}/members`),
  setRole: (orgId: UUID, userId: UUID, role: Role) => patch<Membership>(`/api/orgs/${orgId}/members/${userId}`, { role }),
  removeMember: (orgId: UUID, userId: UUID) => del<void>(`/api/orgs/${orgId}/members/${userId}`),
  invites: (orgId: UUID) => get<Invite[]>(`/api/orgs/${orgId}/invites`),
  createInvite: (orgId: UUID, body: { email?: string; role?: Role } = {}) => post<Invite>(`/api/orgs/${orgId}/invites`, body),
  revokeInvite: (orgId: UUID, inviteId: UUID) => del<void>(`/api/orgs/${orgId}/invites/${inviteId}`),
  projects: (orgId: UUID) => get<Project[]>(`/api/orgs/${orgId}/projects`),
  createProject: (orgId: UUID, body: { name: string; repo_full_name?: string }) => post<Project>(`/api/orgs/${orgId}/projects`, body),
  github: {
    connect: (orgId: UUID) => post<Org>(`/api/orgs/${orgId}/integrations/github/connect`),
    disconnect: (orgId: UUID) => del<Org>(`/api/orgs/${orgId}/integrations/github`),
    repos: (orgId: UUID) => get<{ full_name: string; private?: boolean }[]>(`/api/orgs/${orgId}/integrations/github/repos`),
  },
  notion: {
    connect: (orgId: UUID, body: { notion_token: string; notion_tasks_db_id: string }) => put<Org>(`/api/orgs/${orgId}/integrations/notion`, body),
    disconnect: (orgId: UUID) => del<Org>(`/api/orgs/${orgId}/integrations/notion`),
  },
}

export const inviteApi = {
  preview: (token: string) => get<InvitePreview>(`/api/invites/${token}`),
  accept: (token: string) => post<Org>(`/api/invites/${token}/accept`),
}

/* ── API keys (what an agent's MCP client needs) ────────────────────────── */

export const keyApi = {
  list: () => get<ApiKey[]>('/api/me/api-keys'),
  create: (body: { name?: string; org_id?: UUID; project_id?: UUID } = {}) => post<ApiKeyCreated>('/api/me/api-keys', body),
  revoke: (keyId: UUID) => del<void>(`/api/me/api-keys/${keyId}`),
}

/* ── Projects (= "teams" in the UI) and the board ───────────────────────── */

export const projectApi = {
  list: () => get<Project[]>('/api/projects'),
  get: (id: UUID) => get<Project>(`/api/projects/${id}`),
  agents: (id: UUID) => get<Agent[]>(`/api/projects/${id}/agents`),
  tasks: (id: UUID) => get<Task[]>(`/api/projects/${id}/tasks`),
  claims: (id: UUID, f: { status?: ClaimStatus; agent?: string } = {}) => get<Claim[]>(`/api/projects/${id}/claims${q(f)}`),
  memory: (id: UUID, f: { type?: MemoryType; q?: string } = {}) => get<MemoryEntry[]>(`/api/projects/${id}/memory${q(f)}`),
  clashes: (id: UUID, f: { status?: ClashStatus; severity?: Severity } = {}) => get<Clash[]>(`/api/projects/${id}/clashes${q(f)}`),
  counters: (id: UUID) => get<Counters>(`/api/projects/${id}/counters`),
  verdicts: (id: UUID, limit = 50) => get<unknown[]>(`/api/projects/${id}/verdicts${q({ limit })}`),
  syncGithub: (id: UUID) => post<unknown>(`/api/projects/${id}/integrations/github/sync`),
  syncNotion: (id: UUID) => post<unknown>(`/api/projects/${id}/integrations/notion/sync`),
}

export const claimApi = {
  get: (claimId: UUID) => get<Claim>(`/api/claims/${claimId}`),
}

export const clashApi = {
  get: (clashId: UUID) => get<Clash>(`/api/clashes/${clashId}`),
  /**
   * a_proceeds = the earlier claim (claim_a) wins; b_proceeds = the newer claim (the one told to wait) wins.
   * resolved_by may be "" and the backend fills in the signed-in user's email.
   */
  resolve: (clashId: UUID, body: { resolution: Resolution; note: string; resolved_by?: string }) =>
    post<Clash & { ruling?: ContextItem }>(`/api/clashes/${clashId}/resolve`, { resolved_by: '', ...body }),
}

/* ── Live stream ────────────────────────────────────────────────────────── */

export type StreamEvent =
  | { type: 'hello'; data: { counters: Counters } }
  | { type: 'pong'; data?: unknown }
  | { type: 'claim.created'; data: { claim: Claim; verdict: Verdict } }
  | { type: 'claim.retired'; data: { claim_id: UUID; pr_number?: number | null; merged: boolean } }
  | { type: 'clash.opened'; data: { clash: Clash } }
  | { type: 'clash.resolved'; data: { clash: Clash; auto: boolean; ruling: ContextItem } }
  | { type: 'memory.written'; data: { entry: MemoryEntry } }
  | { type: 'memory.read'; data: { agent: string; question: string; hits: number; tokens_used: number } }
  | { type: 'handoff.filed'; data: { claim: Claim; entry_id: UUID; changed: string[]; untouched: string[]; assumptions: string[]; uncertainties: string[] } }
  | { type: 'pr.opened'; data: { claim_id: UUID; pr_url: string; pr_number: number } }

export interface StreamFrame { id: string; project_id: UUID; ts: string; type: StreamEvent['type']; data: unknown }

/**
 * Opens /ws/projects/{id}. Browsers cannot set headers on WebSockets, so the
 * token goes in ?token=. Events are not persisted: on reconnect, re-fetch
 * claims / clashes / memory / counters, then resume.
 */
export function openProjectStream(projectId: UUID, onEvent: (e: StreamEvent, frame: StreamFrame) => void): () => void {
  const origin = BASE || window.location.origin
  const wsOrigin = origin.replace(/^http/, 'ws')
  const url = `${wsOrigin}/ws/projects/${projectId}${q({ token: auth.token ?? undefined })}`
  let ws: WebSocket | null = null
  let closed = false
  let retry = 1000
  const connect = () => {
    ws = new WebSocket(url)
    ws.onmessage = (m) => {
      const frame = JSON.parse(m.data) as StreamFrame
      onEvent({ type: frame.type, data: frame.data } as StreamEvent, frame)
    }
    ws.onopen = () => { retry = 1000 }
    ws.onclose = () => { if (!closed) setTimeout(connect, (retry = Math.min(retry * 2, 15000))) }
  }
  connect()
  return () => { closed = true; ws?.close() }
}
