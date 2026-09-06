import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  claimApi,
  clashApi,
  openProjectStream,
  projectApi,
  type Agent,
  type Claim,
  type Clash,
  type Counters,
  type EventFrame,
  type MemoryEntry,
  type MemoryType,
  type Resolution,
  type Task,
} from './api'
import { describeError, type Team } from './session'

/**
 * Live data for the selected team: agents, claims, conflicts, memory, tasks,
 * activity and counters, loaded over REST and kept current over the
 * WebSocket. Every write goes through the backend and the resulting event
 * updates the same state, so the screen a human is looking at and the one an
 * agent reacts to are the same data.
 */

export type UiAgentStatus = 'working' | 'reviewing' | 'blocked' | 'idle'
export type UiSeverity = 'HIGH' | 'MEDIUM' | 'LOW'
export type ActivityKind = 'claim' | 'clash' | 'ruling' | 'memory' | 'pr' | 'handoff'

export interface ActivityItem {
  id: string
  kind: ActivityKind
  title: string
  detail: string
  at: string
}

export interface ProjectData {
  team: Team
  loading: boolean
  error: string | null
  live: boolean
  counters: Counters | null
  agents: Agent[]
  claims: Claim[]
  clashes: Clash[]
  memory: MemoryEntry[]
  tasks: Task[]
  activity: ActivityItem[]
  justSavedMemoryId: string | null

  agentById: (id: string) => Agent | undefined
  claimById: (id: string) => Claim | undefined
  agentStatus: (agent: Agent) => UiAgentStatus
  refresh: () => Promise<void>
  resolveClash: (clashId: string, resolution: Resolution, note: string) => Promise<void>
  withdrawClaim: (claimId: string, reason?: string) => Promise<void>
  writeMemory: (input: { type: MemoryType; content: string; concepts: string[]; author: string }) => Promise<void>
  setTasks: React.Dispatch<React.SetStateAction<Task[]>>
}

const ProjectContext = createContext<ProjectData | null>(null)

export function useProject() {
  const value = useContext(ProjectContext)
  if (!value) throw new Error('useProject must be used inside ProjectProvider')
  return value
}

export const severityOf = (clash: Clash): UiSeverity =>
  clash.severity === 'hard' ? 'HIGH' : clash.severity === 'soft' ? 'MEDIUM' : 'LOW'

export const isOpen = (clash: Clash) => clash.status === 'open'

function frameToActivity(frame: EventFrame): ActivityItem | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- untyped event payload
  const d = frame.data as Record<string, any>
  const base = { id: frame.id, at: frame.ts }
  switch (frame.type) {
    case 'claim.created': {
      const claim = d.claim ?? {}
      const verdict = d.verdict ? ` · verdict: ${String(d.verdict).replace(/_/g, ' ')}` : ''
      return {
        ...base,
        kind: 'claim',
        title: `${claim.agent_name ?? 'An agent'} declared "${claim.intent_text ?? ''}"`,
        detail: `${(claim.concepts ?? []).join(', ') || 'no concepts'}${claim.branch ? ` · ${claim.branch}` : ''}${verdict}`,
      }
    }
    case 'claim.retired': {
      const why = d.reason === 'withdrawn' ? 'withdrawn' : d.reason === 'expired' ? 'expired' : d.merged ? 'merged' : 'closed'
      return { ...base, kind: 'claim', title: `Claim retired (${why})`, detail: d.pr_number ? `PR #${d.pr_number}` : `claim ${String(d.claim_id ?? '').slice(0, 8)}` }
    }
    case 'clash.opened': {
      const clash = d.clash ?? {}
      return {
        ...base,
        kind: 'clash',
        title: `Conflict opened: ${clash.title ?? clash.axis ?? ''}`,
        detail: `${clash.agent_a ?? '?'} vs ${clash.agent_b ?? '?'} · ${clash.severity_label ?? clash.severity ?? ''} severity`,
      }
    }
    case 'clash.resolved': {
      const clash = d.clash ?? {}
      const who = d.auto ? 'Auto-resolved' : `${clash.resolved_by ?? 'Someone'} ruled on`
      const how =
        clash.resolution === 'both_with_note' ? 'Both proceed with a note' : clash.resolution === 'a_proceeds' ? `${clash.agent_a} proceeds` : `${clash.agent_b} proceeds`
      return { ...base, kind: 'ruling', title: `${who} "${clash.title ?? clash.axis ?? ''}"`, detail: how }
    }
    case 'memory.written': {
      const entry = d.entry ?? {}
      const kind: ActivityKind = entry.type === 'handoff' ? 'handoff' : entry.type === 'ruling' ? 'ruling' : 'memory'
      const label = entry.type === 'dead_end' ? 'a dead end' : entry.type === 'handoff' ? 'a handoff' : `a ${entry.type}`
      return {
        ...base,
        kind,
        title: `${entry.source_agent ?? 'Consensus'} recorded ${label}`,
        detail: String(entry.title || entry.content || '').slice(0, 120),
      }
    }
    case 'handoff.filed': {
      const claim = d.claim ?? {}
      return { ...base, kind: 'handoff', title: `${claim.agent_name ?? 'An agent'} filed a handoff`, detail: `${(d.changed ?? []).length} changed · ${(d.untouched ?? []).length} untouched` }
    }
    case 'pr.opened':
      return { ...base, kind: 'pr', title: `Pull request #${d.pr_number} opened`, detail: String(d.pr_url ?? '') }
    default:
      return null
  }
}

export function ProjectProvider({ team, children }: { team: Team; children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [counters, setCounters] = useState<Counters | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [claims, setClaims] = useState<Claim[]>([])
  const [clashes, setClashes] = useState<Clash[]>([])
  const [memory, setMemory] = useState<MemoryEntry[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [justSavedMemoryId, setJustSavedMemoryId] = useState<string | null>(null)
  const seq = useRef(0)

  const refresh = useCallback(async () => {
    const mine = ++seq.current
    try {
      const [c, a, cl, cx, m, t, ev] = await Promise.all([
        projectApi.counters(team.id),
        projectApi.agents(team.id),
        projectApi.claims(team.id, { limit: 300 }),
        projectApi.clashes(team.id, { limit: 200 }),
        projectApi.memory(team.id, { limit: 200 }),
        projectApi.tasks(team.id),
        projectApi.activity(team.id, { limit: 150 }),
      ])
      if (mine !== seq.current) return
      setCounters(c)
      setAgents(a)
      setClaims(cl)
      setClashes(cx)
      setMemory(m)
      setTasks(t)
      setActivity(ev.map(frameToActivity).filter((x): x is ActivityItem => x !== null))
      setError(null)
    } catch (problem) {
      if (mine === seq.current) setError(describeError(problem, 'Could not load this team.'))
    } finally {
      if (mine === seq.current) setLoading(false)
    }
  }, [team.id])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  /** Apply one live frame to local state. */
  const applyFrame = useCallback(
    (frame: EventFrame) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- untyped event payload
      const d = frame.data as Record<string, any>
      const item = frameToActivity(frame)
      if (item) setActivity((current) => (current.some((x) => x.id === item.id) ? current : [item, ...current]))

      switch (frame.type) {
        case 'claim.created':
          if (d.claim) setClaims((current) => [d.claim as Claim, ...current.filter((c) => c.id !== d.claim.id)])
          void projectApi.agents(team.id).then(setAgents).catch(() => {})
          void projectApi.counters(team.id).then(setCounters).catch(() => {})
          break
        case 'claim.retired':
          setClaims((current) => current.map((c) => (c.id === d.claim_id ? { ...c, status: 'retired', pr_number: d.pr_number ?? c.pr_number } : c)))
          void projectApi.agents(team.id).then(setAgents).catch(() => {})
          void projectApi.counters(team.id).then(setCounters).catch(() => {})
          break
        case 'clash.opened':
          if (d.clash) setClashes((current) => [d.clash as Clash, ...current.filter((c) => c.id !== d.clash.id)])
          setCounters((c) => (c ? { ...c, open_clashes: c.open_clashes + 1, clashes_caught: c.clashes_caught + 1 } : c))
          break
        case 'clash.resolved':
          if (d.clash) setClashes((current) => current.map((c) => (c.id === d.clash.id ? (d.clash as Clash) : c)))
          setCounters((c) => (c ? { ...c, open_clashes: Math.max(0, c.open_clashes - 1) } : c))
          break
        case 'memory.written':
          if (d.entry) {
            setMemory((current) => (current.some((e) => e.id === d.entry.id) ? current : [d.entry as MemoryEntry, ...current]))
            setCounters((c) => (c ? { ...c, memory_count: c.memory_count + 1 } : c))
          }
          break
        case 'handoff.filed':
          if (d.claim) setClaims((current) => current.map((c) => (c.id === d.claim.id ? (d.claim as Claim) : c)))
          void projectApi.agents(team.id).then(setAgents).catch(() => {})
          break
        case 'pr.opened':
          setClaims((current) => current.map((c) => (c.id === d.claim_id ? { ...c, pr_number: d.pr_number } : c)))
          break
        default:
          break
      }
    },
    [team.id],
  )

  useEffect(() => {
    const stream = openProjectStream(team.id, {
      onEvent: (frame) => {
        if (frame.type === 'hello') {
          const counts = (frame.data as { counters?: Counters }).counters
          if (counts) setCounters(counts)
          return
        }
        applyFrame(frame)
      },
      onOpen: () => {
        setLive(true)
        void refresh()
      },
      onClose: () => setLive(false),
    })
    return () => stream.close()
  }, [team.id, applyFrame, refresh])

  const claimById = useCallback((id: string) => claims.find((c) => c.id === id), [claims])
  const agentById = useCallback((id: string) => agents.find((a) => a.id === id), [agents])

  /** An agent whose newest claim is the waiting side of an open conflict is blocked. */
  const blockedAgentIds = useMemo(() => {
    const ids = new Set<string>()
    for (const clash of clashes) {
      if (!isOpen(clash)) continue
      const waiting = claims.find((c) => c.id === clash.claim_b_id)
      if (waiting) ids.add(waiting.agent_id)
    }
    return ids
  }, [clashes, claims])

  const agentStatus = useCallback(
    (agent: Agent): UiAgentStatus => (blockedAgentIds.has(agent.id) && agent.status === 'working' ? 'blocked' : agent.status),
    [blockedAgentIds],
  )

  const value: ProjectData = {
    team,
    loading,
    error,
    live,
    counters,
    agents,
    claims,
    clashes,
    memory,
    tasks,
    activity,
    justSavedMemoryId,
    agentById,
    claimById,
    agentStatus,
    refresh,
    setTasks,

    async resolveClash(clashId, resolution, note) {
      const out = await clashApi.resolve(clashId, { resolution, note })
      const { ruling, ...clash } = out
      setClashes((current) => current.map((c) => (c.id === clashId ? (clash as Clash) : c)))
      if (ruling) {
        setMemory((current) => (current.some((e) => e.id === ruling.id) ? current : [ruling, ...current]))
        setJustSavedMemoryId(ruling.id)
      }
    },

    async withdrawClaim(claimId, reason) {
      await claimApi.withdraw(claimId, reason)
      setClaims((current) => current.map((c) => (c.id === claimId ? { ...c, status: 'retired' } : c)))
      await refresh()
    },

    async writeMemory({ type, content, concepts, author }) {
      const out = await projectApi.writeMemory(team.id, { agent_name: author, type, content, concepts })
      setJustSavedMemoryId(out.entry_id)
      // The memory.written event carries the full entry; refresh covers the dedup case.
      await refresh()
    },
  }

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}
