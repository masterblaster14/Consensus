/**
 * Typed client for the Consensus backend.
 *
 * Every path and shape here mirrors app/schemas.py and docs/backend-reference.md
 * in the backend repository. The UI says "organisation" and "team"; the backend
 * says `Org` and `Project`. The types keep the backend's words so they match the
 * JSON on the wire.
 */

/* ------------------------------------------------------------------ *
 * Transport
 * ------------------------------------------------------------------ */

/** Empty when the app is served by the backend or proxied by Vite in dev. */
const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? '').replace(/\/$/, '')

const TOKEN_KEY = 'consensus.token'

export const auth = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string) {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* private mode: the session just won't survive a reload */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  },
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly body: unknown

  constructor(status: number, detail: string, body?: unknown) {
    super(`${status} ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.body = body
  }
}

type Query = Record<string, string | number | boolean | undefined | null>

function withQuery(path: string, query?: Query) {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; query?: Query; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.auth !== false) {
    const token = auth.get()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  let res: Response
  try {
    res = await fetch(BASE + withQuery(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'The server could not be reached.')
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  const parsed: unknown = text ? safeJson(text) : undefined
  if (!res.ok) throw new ApiError(res.status, detailOf(parsed) ?? res.statusText, parsed)
  return parsed as T
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function detailOf(body: unknown): string | undefined {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join(', ')
    }
  }
  return typeof body === 'string' ? body : undefined
}

export const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query })
export const post = <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body, query })
export const patch = <T>(path: string, body?: unknown) => request<T>('PATCH', path, { body })
export const put = <T>(path: string, body?: unknown) => request<T>('PUT', path, { body })
export const del = <T>(path: string) => request<T>('DELETE', path)

/* ------------------------------------------------------------------ *
 * Types (mirror app/schemas.py)
 * ------------------------------------------------------------------ */

export type Role = 'admin' | 'member'
export type MemberStatus = 'active' | 'restricted'
export type ClaimStatus = 'open' | 'in_review' | 'retired'
export type ClashSeverity = 'hard' | 'soft' | 'context' | 'clear'
export type ClashStatus = 'open' | 'resolved' | 'auto_resolved'
export type Resolution = 'a_proceeds' | 'b_proceeds' | 'both_with_note'
export type MemoryType = 'ruling' | 'decision' | 'discovery' | 'dead_end' | 'handoff'
export type AgentStatus = 'working' | 'reviewing' | 'idle'
export type TaskStatus = 'open' | 'in_progress' | 'done'
export type Verdict = 'proceed' | 'proceed_with_context' | 'wait'

export interface User {
  id: string
  email: string
  name: string
  avatar_url: string | null
  github_login: string | null
  created_at: string | null
}

export interface Membership {
  org_id: string
  org_name: string | null
  org_slug: string | null
  role: Role
  status: MemberStatus
  user_id: string
  user_email: string | null
  user_name: string | null
  user_avatar_url: string | null
}

export interface Me {
  user: User
  memberships: Membership[]
}

export interface TokenOut {
  token: string
  token_type: string
  me: Me
}

export interface AuthProviders {
  github: boolean
  magic_link: boolean
  dev_login: boolean
}

export interface OrgIntegrations {
  github: { connected: boolean; connected_by: string | null; webhooks?: Record<string, WebhookStatus> }
  notion: { connected: boolean; tasks_db_id: string | null }
}

export interface Org {
  id: string
  name: string
  slug: string
  auto_join_domain: string | null
  created_at: string | null
  role: Role | null
  integrations: OrgIntegrations | null
}

export interface OrgSummary {
  projects: number
  repositories: number
  members: number
  agents: number
  active_agents: number
  open_claims: number
  open_clashes: number
  memory_count: number
  tokens_saved: number
}

export interface Invite {
  id: string
  org_id: string
  org_name: string | null
  email: string | null
  role: Role
  token: string | null
  url: string | null
  expires_at: string | null
  accepted_at: string | null
  email_sent: boolean | null
}

export interface WebhookStatus {
  registered: boolean
  hook_id: number | null
  url: string | null
  reason: string | null
}

export interface Project {
  id: string
  org_id: string | null
  name: string
  repo_full_name: string | null
  created_at: string | null
  archived_at: string | null
  webhook_id: number | null
  /** Only on responses to a write that attached a repository. */
  webhook: WebhookStatus | null
}

export interface ClaimBrief {
  id: string
  intent_text: string
  status: ClaimStatus
  branch: string | null
  task_ref: string | null
  pr_number: number | null
  created_at: string | null
}

export interface Agent {
  id: string
  project_id: string
  name: string
  developer_name: string
  user_id: string | null
  last_seen: string | null
  status: AgentStatus
  open_claims: number
  current_claim: ClaimBrief | null
}

export interface Stance {
  concepts: string[]
  error_handling: string | null
  auth_check: string | null
  data_access: string | null
  api_shape: string | null
  summary: string
}

export interface Claim {
  id: string
  project_id: string
  agent_id: string
  agent_name: string | null
  developer_name: string | null
  task_id: string | null
  task_ref: string | null
  intent_text: string
  stance: Stance
  concepts: string[]
  branch: string | null
  pr_number: number | null
  status: ClaimStatus
  created_at: string | null
  resolved_at: string | null
}

export interface MemoryEntry {
  id: string
  project_id: string
  type: MemoryType
  title: string
  content: string
  concepts: string[]
  axis: string | null
  source_agent_id: string | null
  source_agent: string | null
  related_claim_id: string | null
  created_at: string | null
}

export interface Clash {
  id: string
  project_id: string
  claim_a_id: string
  claim_b_id: string
  agent_a: string | null
  agent_b: string | null
  intent_a: string | null
  intent_b: string | null
  position_a: string | null
  position_b: string | null
  axis: string
  shared_concepts: string[]
  severity: ClashSeverity
  status: ClashStatus
  resolution: Resolution | null
  resolution_note: string | null
  resolved_by: string | null
  created_at: string | null
  title: string
  explanation: string
  severity_label: string
}

export interface Counters {
  tokens_saved: number
  clashes_caught: number
  memory_count: number
  open_claims: number
  open_clashes: number
  agents: number
}

export interface VerdictLog {
  id: string
  claim_id: string | null
  verdict: Verdict
  duration_ms: number
  detail: Record<string, unknown>
  created_at: string | null
}

export interface Task {
  id: string
  project_id: string
  external_ref: string | null
  notion_page_id: string | null
  title: string
  status: TaskStatus
  assignee_agent_id: string | null
  assignee_agent: string | null
  created_at: string | null
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  org_id: string
  project_id: string | null
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

/** `key` and `mcp_url` come back once, at creation, and never again. */
export interface ApiKeyCreated extends ApiKey {
  key: string
  mcp_url: string
}

export interface GithubRepo {
  full_name: string
  private: boolean
  default_branch: string | null
}

export interface ContextItem {
  type: string
  content: string
  source: string | null
  entry_id: string | null
  similarity: number | null
}

export interface StatusOut {
  project_id: string
  agents: string[]
  claims: (ClaimBrief & { agent_name: string | null })[]
  waiting_on: Clash[]
  blocking: Clash[]
}

/** One persisted event frame; the same shape the WebSocket delivers. */
export interface EventFrame {
  id: string
  type: string
  project_id: string
  ts: string
  data: Record<string, unknown>
}

/* ------------------------------------------------------------------ *
 * Auth
 * ------------------------------------------------------------------ */

export const authApi = {
  providers: () => request<AuthProviders>('GET', '/api/auth/providers', { auth: false }),

  /** Returns the GitHub URL to send the browser to. GitHub bounces back to FRONTEND_URL/auth/callback#token=<jwt>&next=<redirect_to>. */
  githubStart: (redirectTo?: string) =>
    request<{ url: string; state: string }>('GET', withQuery('/api/auth/github/start', { redirect_to: redirectTo }), { auth: false }),

  magicLink: (email: string, name?: string) =>
    request<{ ok: boolean; sent: boolean; expires_in_minutes: number; dev_link?: string; dev_token?: string }>(
      'POST',
      '/api/auth/magic-link',
      { body: { email, name }, auth: false },
    ),
  magicVerify: (token: string) => request<TokenOut>('POST', '/api/auth/magic-link/verify', { body: { token }, auth: false }),

  /** DEV_AUTH=true only: signs in as any email, creating the account if needed. */
  devLogin: (email: string, name?: string) => request<TokenOut>('POST', '/api/auth/dev-login', { body: { email, name }, auth: false }),

  me: () => get<Me>('/api/auth/me'),
}

/* ------------------------------------------------------------------ *
 * Organisations, members, invites, integrations
 * ------------------------------------------------------------------ */

export const orgApi = {
  list: () => get<Org[]>('/api/orgs'),
  create: (body: { name: string; slug?: string; auto_join_domain?: string }) => post<Org>('/api/orgs', body),
  get: (orgId: string) => get<Org>(`/api/orgs/${orgId}`),
  update: (orgId: string, body: { name?: string; auto_join_domain?: string | null }) => patch<Org>(`/api/orgs/${orgId}`, body),
  summary: (orgId: string) => get<OrgSummary>(`/api/orgs/${orgId}/summary`),

  members: (orgId: string) => get<Membership[]>(`/api/orgs/${orgId}/members`),
  updateMember: (orgId: string, userId: string, body: { role?: Role; status?: MemberStatus }) =>
    patch<Membership>(`/api/orgs/${orgId}/members/${userId}`, body),
  removeMember: (orgId: string, userId: string) => del<void>(`/api/orgs/${orgId}/members/${userId}`),

  createInvite: (orgId: string, body: { email?: string; role?: Role }) => post<Invite>(`/api/orgs/${orgId}/invites`, body),
  invites: (orgId: string) => get<Invite[]>(`/api/orgs/${orgId}/invites`),
  revokeInvite: (orgId: string, inviteId: string) => del<void>(`/api/orgs/${orgId}/invites/${inviteId}`),

  projects: (orgId: string, includeArchived = false) =>
    get<Project[]>(`/api/orgs/${orgId}/projects`, { include_archived: includeArchived || undefined }),
  createProject: (orgId: string, body: { name: string; repo_full_name?: string }) => post<Project>(`/api/orgs/${orgId}/projects`, body),
  archiveProject: (orgId: string, projectId: string) => del<void>(`/api/orgs/${orgId}/projects/${projectId}`),
  restoreProject: (orgId: string, projectId: string) => post<Project>(`/api/orgs/${orgId}/projects/${projectId}/restore`),

  github: {
    connect: (orgId: string) => post<Org>(`/api/orgs/${orgId}/integrations/github/connect`),
    disconnect: (orgId: string) => del<Org>(`/api/orgs/${orgId}/integrations/github`),
    repos: (orgId: string) => get<GithubRepo[]>(`/api/orgs/${orgId}/integrations/github/repos`),
  },
  notion: {
    connect: (orgId: string, body: { notion_token: string; notion_tasks_db_id: string }) => put<Org>(`/api/orgs/${orgId}/integrations/notion`, body),
    disconnect: (orgId: string) => del<Org>(`/api/orgs/${orgId}/integrations/notion`),
  },
}

export const inviteApi = {
  /** Public. The token is the last path segment of the invite URL. */
  preview: (token: string) => request<Invite>('GET', `/api/invites/${token}`, { auth: false }),
  accept: (token: string) => post<Org>(`/api/invites/${token}/accept`),
}

/* ------------------------------------------------------------------ *
 * API keys (what an agent's MCP client needs)
 * ------------------------------------------------------------------ */

export const keyApi = {
  list: () => get<ApiKey[]>('/api/me/api-keys'),
  create: (body: { name?: string; org_id?: string; project_id?: string }) => post<ApiKeyCreated>('/api/me/api-keys', body),
  revoke: (keyId: string) => del<void>(`/api/me/api-keys/${keyId}`),
}

/* ------------------------------------------------------------------ *
 * Projects (= "teams" in the UI) and the board
 * ------------------------------------------------------------------ */

export const projectApi = {
  list: (includeArchived = false) => get<Project[]>('/api/projects', { include_archived: includeArchived || undefined }),
  get: (id: string) => get<Project>(`/api/projects/${id}`),
  update: (id: string, body: { name?: string; repo_full_name?: string | null }) => patch<Project>(`/api/projects/${id}`, body),
  archive: (id: string) => del<void>(`/api/projects/${id}`),
  restore: (id: string) => post<Project>(`/api/projects/${id}/restore`),
  registerWebhook: (id: string) => post<WebhookStatus>(`/api/projects/${id}/integrations/github/webhook`),

  counters: (id: string) => get<Counters>(`/api/projects/${id}/counters`),
  agents: (id: string) => get<Agent[]>(`/api/projects/${id}/agents`),
  status: (id: string, agent?: string) => get<StatusOut>(`/api/projects/${id}/status`, { agent }),
  claims: (id: string, query?: { status?: ClaimStatus; agent?: string; limit?: number }) => get<Claim[]>(`/api/projects/${id}/claims`, query),
  clashes: (id: string, query?: { status?: ClashStatus; severity?: ClashSeverity; limit?: number }) =>
    get<Clash[]>(`/api/projects/${id}/clashes`, query),
  /** `q` is a semantic search over the entries, not a substring match. */
  memory: (id: string, query?: { type?: MemoryType; q?: string; limit?: number }) => get<MemoryEntry[]>(`/api/projects/${id}/memory`, query),
  writeMemory: (id: string, body: { agent_name: string; type: MemoryType; content: string; concepts?: string[] }) =>
    post<{ entry_id: string; deduplicated: boolean }>(`/api/projects/${id}/memory`, body),
  activity: (id: string, query?: { limit?: number; before?: string; type?: string }) => get<EventFrame[]>(`/api/projects/${id}/activity`, query),
  verdicts: (id: string, limit = 100) => get<VerdictLog[]>(`/api/projects/${id}/verdicts`, { limit }),

  tasks: (id: string, status?: TaskStatus) => get<Task[]>(`/api/projects/${id}/tasks`, { status }),
  createTask: (id: string, body: { title: string; external_ref?: string; status?: TaskStatus }) => post<Task>(`/api/projects/${id}/tasks`, body),
  updateTask: (id: string, taskId: string, body: { title?: string; external_ref?: string; status?: TaskStatus; assignee_agent?: string }) =>
    patch<Task>(`/api/projects/${id}/tasks/${taskId}`, body),
  deleteTask: (id: string, taskId: string) => del<void>(`/api/projects/${id}/tasks/${taskId}`),

  syncGithub: (id: string) => post<{ claims_created: number }>(`/api/projects/${id}/integrations/github/sync`),
  syncNotion: (id: string) => post<{ tasks_upserted: number }>(`/api/projects/${id}/integrations/notion/sync`),
}

export const claimApi = {
  get: (claimId: string) => get<Claim>(`/api/claims/${claimId}`),
  withdraw: (claimId: string, reason?: string) =>
    post<{ claim_id: string; status: string; released_clashes: string[] }>(`/api/claims/${claimId}/withdraw`, { reason }),
}

export const clashApi = {
  get: (clashId: string) => get<Clash>(`/api/clashes/${clashId}`),
  /**
   * a_proceeds = the earlier claim (claim_a) proceeds; b_proceeds = the newer one (the claim that
   * received `wait`). `resolved_by` is filled in by the backend from the signed-in user.
   */
  resolve: (clashId: string, body: { resolution: Resolution; note: string }) =>
    post<Clash & { ruling: MemoryEntry | null }>(`/api/clashes/${clashId}/resolve`, { ...body, resolved_by: '' }),
}

/* ------------------------------------------------------------------ *
 * WebSocket
 * ------------------------------------------------------------------ */

export interface Stream {
  close(): void
}

function wsOrigin() {
  if (BASE) return BASE.replace(/^http/, 'ws')
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`
}

/**
 * Live project feed at /ws/projects/{id}. Browsers cannot set headers on a
 * WebSocket, so the token travels as ?token=. Reconnects with backoff; `onOpen`
 * fires on every successful connect, which is the cue to re-fetch so nothing
 * missed while the socket was down stays missing. Events are not persisted on
 * the socket side; the activity endpoint has the history.
 */
export function openProjectStream(
  projectId: string,
  handlers: { onEvent: (frame: EventFrame) => void; onOpen?: () => void; onClose?: () => void },
): Stream {
  let socket: WebSocket | null = null
  let retry = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false

  const connect = () => {
    if (closed) return
    const url = withQuery(`${wsOrigin()}/ws/projects/${projectId}`, { token: auth.get() })
    socket = new WebSocket(url)
    socket.onopen = () => {
      retry = 0
      handlers.onOpen?.()
    }
    socket.onmessage = (message) => {
      const data = safeJson(String(message.data))
      if (data && typeof data === 'object' && 'type' in data) handlers.onEvent(data as EventFrame)
    }
    socket.onclose = () => {
      handlers.onClose?.()
      if (closed) return
      timer = setTimeout(connect, Math.min(30_000, 1_000 * 2 ** retry++))
    }
    socket.onerror = () => socket?.close()
  }

  connect()
  return {
    close() {
      closed = true
      if (timer) clearTimeout(timer)
      socket?.close()
    },
  }
}
