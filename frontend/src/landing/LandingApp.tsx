import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import heroArt from '../assets/hero.svg'
import type { Invite } from '../lib/api'
import { Icon } from '../lib/icons'
import { LoadingScreen, describeError, firstName, inviteTokenFrom, useSession } from '../lib/session'
import { ThemeToggle } from '../lib/theme'
import './landing.css'

/* ===================================================================
   The public half: marketing page, sign in, the auth return routes,
   invites and onboarding. Team and member management lives inside the
   dashboard behind the admin role.
   =================================================================== */

const MCP_URL = `${window.location.origin}/mcp`

function Notice({ tone, children }: { tone: 'info' | 'warn' | 'danger' | 'success'; children: React.ReactNode }) {
  const glyph = tone === 'success' ? <Icon.Check size={18} /> : tone === 'info' ? <Icon.Info /> : <Icon.Alert />
  return (
    <div className={`notice notice--${tone}`}>
      {glyph}
      <div>{children}</div>
    </div>
  )
}

function BackLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="back-link">
      <Icon.ArrowLeft />
      {children}
    </Link>
  )
}

/** Only ever redirect inside this app. */
function useNextTarget(fallback = '/app/dashboard') {
  const [params] = useSearchParams()
  const raw = params.get('next')
  if (!raw) return fallback
  const decoded = decodeURIComponent(raw)
  return decoded.startsWith('/') && !decoded.startsWith('//') ? decoded : fallback
}

/* -------------------------------------------------------------------
   Root
   ------------------------------------------------------------------- */

export default function LandingApp() {
  return (
    <div className="page-root">
      <TopNav />
      <Routes>
        <Route index element={<MarketingPage />} />
        <Route path="signin" element={<SignInPage mode="signin" />} />
        <Route path="signup" element={<SignInPage mode="signup" />} />
        <Route path="auth/callback" element={<AuthCallbackPage />} />
        <Route path="auth/magic" element={<MagicLinkPage />} />
        <Route path="invite/:token" element={<InvitePage />} />
        <Route path="onboarding" element={<OnboardingChoice />} />
        <Route path="onboarding/create-org" element={<CreateOrgPage />} />
        <Route path="onboarding/join-org" element={<JoinOrgPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

/* -------------------------------------------------------------------
   Top navigation
   ------------------------------------------------------------------- */

const NAV_LINKS = [
  { href: '/#how', label: 'How it works' },
  { href: '/#features', label: 'Features' },
  { href: '/#pricing', label: 'Pricing' },
  { href: '/#start', label: 'Get started' },
]

function TopNav() {
  const { status, org, signOut } = useSession()
  const [mobileOpen, setMobileOpen] = useState(false)
  const navigate = useNavigate()
  const signedIn = status === 'ready'
  const appHref = org ? '/app/dashboard' : '/onboarding'

  const actions = signedIn ? (
    <>
      <button
        type="button"
        className="ghost-button"
        onClick={() => {
          setMobileOpen(false)
          signOut()
          navigate('/')
        }}
      >
        Sign out
      </button>
      <Link to={appHref} className="primary-button" onClick={() => setMobileOpen(false)}>
        {org ? 'Open dashboard' : 'Finish setup'}
        <Icon.ArrowRight size={16} />
      </Link>
    </>
  ) : (
    <>
      <Link to="/signin" className="ghost-button" onClick={() => setMobileOpen(false)}>
        Sign in
      </Link>
      <Link to="/signup" className="primary-button" onClick={() => setMobileOpen(false)}>
        Get started
      </Link>
    </>
  )

  return (
    <header className="topnav">
      <div className="topnav__inner">
        <Link to="/" className="brand">
          <span className="brand__mark">
            <Icon.Logo />
          </span>
          Consensus
        </Link>
        <nav className="topnav__links">
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href}>
              {link.label}
            </a>
          ))}
        </nav>
        <div className="topnav__actions">
          <ThemeToggle />
          {actions}
        </div>
        <button type="button" className="topnav__burger" aria-label={mobileOpen ? 'Close menu' : 'Open menu'} aria-expanded={mobileOpen} onClick={() => setMobileOpen((open) => !open)}>
          {mobileOpen ? <Icon.Close /> : <Icon.Menu />}
        </button>
      </div>
      <div className={`topnav__mobile${mobileOpen ? ' is-open' : ''}`}>
        {NAV_LINKS.map((link) => (
          <a key={link.href} href={link.href} onClick={() => setMobileOpen(false)}>
            {link.label}
          </a>
        ))}
        <div className="topnav__mobile-actions">{actions}</div>
      </div>
    </header>
  )
}

/* -------------------------------------------------------------------
   Sign in (accounts are created on first sign-in, so sign-up is the same
   screen with different words)
   ------------------------------------------------------------------- */

function SignInPage({ mode }: { mode: 'signin' | 'signup' }) {
  const { status, org, providers, startGithub, devLogin, requestMagicLink } = useSession()
  const navigate = useNavigate()
  const next = useNextTarget()

  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState<'github' | 'magic' | 'dev' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<{ email: string; devLink?: string } | null>(null)

  if (status === 'loading') return <LoadingScreen label="Checking your session…" />
  if (status === 'ready') return <Navigate to={org ? next : '/onboarding'} replace />

  const github = async () => {
    setBusy('github')
    setError(null)
    try {
      await startGithub(next)
    } catch (problem) {
      setError(describeError(problem))
      setBusy(null)
    }
  }

  const magic = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError('Enter a valid email address.')
      return
    }
    setBusy('magic')
    setError(null)
    try {
      const out = await requestMagicLink(email.trim(), name.trim() || undefined)
      setSent({ email: email.trim(), devLink: out.devLink })
    } catch (problem) {
      setError(describeError(problem))
    } finally {
      setBusy(null)
    }
  }

  const dev = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError('Enter a valid email address.')
      return
    }
    setBusy('dev')
    setError(null)
    try {
      const account = await devLogin(email.trim(), name.trim() || undefined)
      navigate(account.memberships.length > 0 ? next : '/onboarding', { replace: true })
    } catch (problem) {
      setError(describeError(problem))
      setBusy(null)
    }
  }

  const noProviders = providers && !providers.github && !providers.magic_link && !providers.dev_login

  return (
    <main className="centered">
      <div className="panel">
        <div className="panel__head">
          <h1>{mode === 'signup' ? 'Create your account' : 'Sign in to Consensus'}</h1>
          <p>{mode === 'signup' ? 'Your account is created the first time you sign in. Two minutes to your first coordinated agent.' : 'Your agents are waiting on a decision.'}</p>
        </div>

        {error && <Notice tone="danger">{error}</Notice>}
        {!providers && <Notice tone="info">Checking which sign-in methods are available…</Notice>}
        {noProviders && <Notice tone="warn">No sign-in method is configured on this server. An administrator needs to set up GitHub OAuth or email.</Notice>}

        {providers?.github && (
          <button type="button" className="gh-button" data-state={busy === 'github' ? 'loading' : 'idle'} disabled={busy !== null} onClick={github}>
            {busy === 'github' ? (
              <>
                <Icon.Spinner size={17} className="spin" />
                Taking you to GitHub…
              </>
            ) : (
              <>
                <Icon.GitHub size={18} />
                {mode === 'signup' ? 'Sign up with GitHub' : 'Continue with GitHub'}
              </>
            )}
          </button>
        )}

        {providers?.github && (providers.magic_link || providers.dev_login) && <div className="divider">or with email</div>}

        {sent ? (
          <Notice tone="success">
            <b>Check your inbox.</b> We sent a sign-in link to {sent.email}. It works for 15 minutes.
            {sent.devLink && (
              <>
                {' '}
                <br />
                <span style={{ fontSize: '0.8125rem' }}>
                  Development mode: <a href={sent.devLink}>open the link here</a>.
                </span>
              </>
            )}
          </Notice>
        ) : (
          (providers?.magic_link || providers?.dev_login) && (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void (providers.dev_login ? dev() : magic())
              }}
            >
              {mode === 'signup' && (
                <label className="field">
                  <span className="field__label">Your name</span>
                  <input className="input" placeholder="Priya Nair" value={name} onChange={(event) => setName(event.target.value)} />
                </label>
              )}
              <label className="field">
                <span className="field__label">Email</span>
                <div className="input-wrap">
                  <Icon.Mail size={16} />
                  <input
                    className={`input${error ? ' is-invalid' : ''}`}
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(event) => {
                      setEmail(event.target.value)
                      setError(null)
                    }}
                    autoFocus={!providers?.github}
                  />
                </div>
                {providers.dev_login && <p className="field__hint">Development sign-in: this server accepts any email and creates the account on the spot.</p>}
              </label>
              <button type="submit" className="primary-button btn-block btn-lg" disabled={busy !== null}>
                {busy === 'magic' || busy === 'dev' ? (
                  <>
                    <Icon.Spinner size={17} className="spin" />
                    {providers.dev_login ? 'Signing in…' : 'Sending link…'}
                  </>
                ) : (
                  <>
                    {providers.dev_login ? 'Sign in' : 'Email me a sign-in link'}
                    <Icon.ArrowRight size={16} />
                  </>
                )}
              </button>
            </form>
          )
        )}

        <div className="panel__foot">
          {mode === 'signup' ? (
            <>
              <span>Already have an account?</span>
              <Link to={`/signin${next !== '/app/dashboard' ? `?next=${encodeURIComponent(next)}` : ''}`}>Sign in</Link>
            </>
          ) : (
            <>
              <span>New to Consensus?</span>
              <Link to="/signup">Create an account</Link>
            </>
          )}
        </div>
      </div>
    </main>
  )
}

/** GitHub sends the browser back here with #token=<jwt>&next=<path>. */
function AuthCallbackPage() {
  const { completeToken } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(location.hash.replace(/^#/, ''))
    const token = params.get('token')
    const next = params.get('next') || '/app/dashboard'
    if (!token) {
      setError('No sign-in token in the address. Start again from the sign-in page.')
      return
    }
    completeToken(token)
      .then((account) => {
        window.history.replaceState(null, '', location.pathname)
        const target = next.startsWith('/') && !next.startsWith('//') ? next : '/app/dashboard'
        navigate(account.memberships.length > 0 ? target : '/onboarding', { replace: true })
      })
      .catch((problem) => setError(describeError(problem)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <main className="centered">
        <div className="panel">
          <div className="panel__head">
            <h1>Sign-in did not complete</h1>
          </div>
          <Notice tone="danger">{error}</Notice>
          <Link to="/signin" className="primary-button btn-block">
            Back to sign in
          </Link>
        </div>
      </main>
    )
  }
  return <LoadingScreen label="Finishing sign-in…" />
}

/** The emailed link lands here with ?token=. */
function MagicLinkPage() {
  const { verifyMagic } = useSession()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = params.get('token')
    if (!token) {
      setError('This link is missing its token.')
      return
    }
    verifyMagic(token)
      .then((account) => navigate(account.memberships.length > 0 ? '/app/dashboard' : '/onboarding', { replace: true }))
      .catch((problem) => setError(describeError(problem, 'This link is invalid, used or expired.')))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <main className="centered">
        <div className="panel">
          <div className="panel__head">
            <h1>That link did not work</h1>
          </div>
          <Notice tone="danger">{error}</Notice>
          <Link to="/signin" className="primary-button btn-block">
            Request a new one
          </Link>
        </div>
      </main>
    )
  }
  return <LoadingScreen label="Signing you in…" />
}

/* -------------------------------------------------------------------
   Invites
   ------------------------------------------------------------------- */

function InvitePage() {
  const { token = '' } = useParams()
  const { status, previewInvite, acceptInvite } = useSession()
  const navigate = useNavigate()
  const [preview, setPreview] = useState<Invite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    previewInvite(token)
      .then(setPreview)
      .catch((problem) => setError(describeError(problem, 'This invite is invalid, used or expired.')))
  }, [token, previewInvite])

  const accept = async () => {
    setBusy(true)
    setError(null)
    try {
      await acceptInvite(token)
      navigate('/app/dashboard', { replace: true })
    } catch (problem) {
      setError(describeError(problem))
      setBusy(false)
    }
  }

  return (
    <main className="centered">
      <div className="panel">
        <div className="panel__head">
          <h1>{preview ? `Join ${preview.org_name}` : 'Invitation'}</h1>
          <p>{preview ? `You were invited as ${preview.role === 'admin' ? 'an admin' : 'a member'}${preview.email ? ` (${preview.email})` : ''}.` : 'Checking the invite…'}</p>
        </div>
        {error && <Notice tone="danger">{error}</Notice>}
        {preview && status === 'anonymous' && (
          <>
            <Notice tone="info">Sign in first. You will come straight back here.</Notice>
            <Link to={`/signin?next=${encodeURIComponent(`/invite/${token}`)}`} className="primary-button btn-block btn-lg">
              Sign in to accept
              <Icon.ArrowRight size={16} />
            </Link>
          </>
        )}
        {preview && status === 'ready' && (
          <button type="button" className="primary-button btn-block btn-lg" disabled={busy} onClick={accept}>
            {busy ? (
              <>
                <Icon.Spinner size={17} className="spin" />
                Joining…
              </>
            ) : (
              <>
                Accept and open the dashboard
                <Icon.ArrowRight size={16} />
              </>
            )}
          </button>
        )}
        {status === 'loading' && <LoadingScreen label="Checking your session…" />}
      </div>
    </main>
  )
}

/* -------------------------------------------------------------------
   Onboarding: signed-in accounts that have no organisation yet
   ------------------------------------------------------------------- */

function useOnboardingGuard() {
  const { status } = useSession()
  if (status === 'loading') return <LoadingScreen />
  if (status === 'anonymous') return <Navigate to="/signin?next=%2Fonboarding" replace />
  return null
}

function OnboardingChoice() {
  const blocked = useOnboardingGuard()
  const { user, org } = useSession()
  if (blocked) return blocked

  return (
    <main className="centered">
      <div className="panel">
        <div className="panel__head">
          <h1>Welcome, {firstName(user?.name ?? '')}</h1>
          <p>Are you starting a new organisation, or joining one that already exists?</p>
        </div>
        <div className="choice-grid">
          <Link className="choice" to="/onboarding/create-org">
            <span className="choice__icon">
              <Icon.Building />
            </span>
            <span>
              <b>Create an organisation</b>
              <span>You become its admin: create teams, invite people, issue keys.</span>
            </span>
            <span className="choice__arrow">
              <Icon.ArrowRight />
            </span>
          </Link>
          <Link className="choice" to="/onboarding/join-org">
            <span className="choice__icon">
              <Icon.UserPlus />
            </span>
            <span>
              <b>Join an organisation</b>
              <span>Paste the invite link a teammate sent you.</span>
            </span>
            <span className="choice__arrow">
              <Icon.ArrowRight />
            </span>
          </Link>
        </div>
        {org && (
          <div className="panel__foot">
            <span>Already in {org.name}?</span>
            <Link to="/app/dashboard">Go to your dashboard</Link>
          </div>
        )}
      </div>
    </main>
  )
}

function CreateOrgPage() {
  const blocked = useOnboardingGuard()
  const { createOrg } = useSession()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (blocked) return blocked

  return (
    <main className="centered">
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault()
          if (!name.trim()) {
            setError('Give your organisation a name.')
            return
          }
          setBusy(true)
          setError(null)
          createOrg({ name, domain })
            .then(() => navigate('/app/dashboard', { replace: true }))
            .catch((problem) => {
              setError(describeError(problem))
              setBusy(false)
            })
        }}
      >
        <BackLink to="/onboarding">Back</BackLink>
        <div className="panel__head">
          <h1>Create your organisation</h1>
          <p>This is the container for your teams, members and agents. You'll be its admin.</p>
        </div>
        <label className="field">
          <span className="field__label">Organisation name</span>
          <input
            className={`input${error ? ' is-invalid' : ''}`}
            placeholder="Acme Corp"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              setError(null)
            }}
            autoFocus
          />
          {error && (
            <span className="field__error">
              <Icon.Alert size={14} />
              {error}
            </span>
          )}
        </label>
        <label className="field">
          <span className="field__label">Email domain (optional)</span>
          <div className="input-wrap">
            <Icon.Globe size={16} />
            <input className="input" placeholder="acme.com" value={domain} onChange={(event) => setDomain(event.target.value)} />
          </div>
          <p className="field__hint">Anyone signing in with a verified email at this domain joins automatically, no invite needed.</p>
        </label>
        <button type="submit" className="primary-button btn-block btn-lg" disabled={busy}>
          {busy ? (
            <>
              <Icon.Spinner size={17} className="spin" />
              Creating…
            </>
          ) : (
            <>
              Create organisation
              <Icon.ArrowRight size={16} />
            </>
          )}
        </button>
      </form>
    </main>
  )
}

function JoinOrgPage() {
  const blocked = useOnboardingGuard()
  const { previewInvite, acceptInvite } = useSession()
  const navigate = useNavigate()
  const [link, setLink] = useState('')
  const [preview, setPreview] = useState<Invite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const token = inviteTokenFrom(link)

  useEffect(() => {
    setPreview(null)
    if (!token) return
    let cancelled = false
    const timer = setTimeout(() => {
      previewInvite(token)
        .then((p) => {
          if (!cancelled) setPreview(p)
        })
        .catch((problem) => {
          if (!cancelled) setError(describeError(problem, 'That invite is invalid, used or expired.'))
        })
    }, 350)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [token, previewInvite])

  if (blocked) return blocked

  return (
    <main className="centered">
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault()
          if (!token) {
            setError("That doesn't look like a Consensus invite link.")
            return
          }
          setBusy(true)
          setError(null)
          acceptInvite(token)
            .then(() => navigate('/app/dashboard', { replace: true }))
            .catch((problem) => {
              setError(describeError(problem))
              setBusy(false)
            })
        }}
      >
        <BackLink to="/onboarding">Back</BackLink>
        <div className="panel__head">
          <h1>Join an organisation</h1>
          <p>Paste the invite link your admin sent you.</p>
        </div>
        <label className="field">
          <span className="field__label">Invite link</span>
          <input
            className={`input input-mono${error ? ' is-invalid' : ''}`}
            placeholder={`${window.location.origin}/invite/…`}
            value={link}
            onChange={(event) => {
              setLink(event.target.value)
              setError(null)
            }}
            autoFocus
          />
          {error && (
            <span className="field__error">
              <Icon.Alert size={14} />
              {error}
            </span>
          )}
        </label>
        {preview && (
          <Notice tone="info">
            You're joining <b>{preview.org_name}</b> as {preview.role === 'admin' ? 'an admin' : 'a member'}.
          </Notice>
        )}
        <button type="submit" className="primary-button btn-block btn-lg" disabled={!token || busy}>
          {busy ? (
            <>
              <Icon.Spinner size={17} className="spin" />
              Joining…
            </>
          ) : (
            <>
              Join
              <Icon.ArrowRight size={16} />
            </>
          )}
        </button>
      </form>
    </main>
  )
}

/* -------------------------------------------------------------------
   Marketing page
   ------------------------------------------------------------------- */

const FEATURES = [
  { icon: <Icon.Layers size={20} />, title: 'One claim board', body: 'Every agent files what it is about to do before it writes. Intent, concepts, branch and PR, visible to the whole team.' },
  { icon: <Icon.Bolt size={20} />, title: 'Conflicts caught early', body: 'Plans are compared on what they mean, not which files they touch. A clash opens before the code exists.' },
  { icon: <Icon.Scale size={20} />, title: 'You arbitrate once', body: 'See both plans side by side, pick who proceeds, leave a note. The ruling is applied automatically the next time the same conflict comes up.' },
  { icon: <Icon.Brain size={20} />, title: 'Memory they all read', body: 'Rulings, decisions, discoveries, dead ends and handoffs. Searchable by meaning, not keywords.' },
  { icon: <Icon.Radio size={20} />, title: 'Live by default', body: 'A WebSocket stream per team pushes claims, clashes and rulings to every open dashboard within a second.' },
  { icon: <Icon.Plug size={20} />, title: 'Drops into your stack', body: 'MCP server for the agent, GitHub for repos and PRs, Notion for tasks. No new editor to learn.' },
]

const PLANS = [
  { name: 'Solo', price: '$0', unit: 'forever', blurb: 'For one developer trying multi-agent work for the first time.', features: ['1 team', '3 connected agents', '30-day shared memory', 'Conflict detection', 'Community support'], cta: 'Start free', featured: false },
  { name: 'Team', price: '$29', unit: 'per developer / month', blurb: 'For teams running several agents against the same repository.', features: ['Unlimited teams', 'Unlimited agents', 'Unbounded memory + semantic search', 'Human arbitration & rulings', 'GitHub and Notion integrations', 'Email support'], cta: 'Start 14-day trial', featured: true },
  { name: 'Enterprise', price: 'Custom', unit: 'annual', blurb: 'For orgs that need self-hosting, SSO and an audit trail.', features: ['Everything in Team', 'SSO / SAML and SCIM', 'Self-hosted or private cloud', 'Audit log export', 'Dedicated support engineer'], cta: 'Talk to us', featured: false },
]

function MarketingPage() {
  const { status, org } = useSession()
  const startHref = status === 'ready' ? (org ? '/app/dashboard' : '/onboarding') : '/signup'

  return (
    <main>
      <section className="hero">
        <div className="wrap hero__grid">
          <div>
            <span className="eyebrow">
              <Icon.Bolt size={13} />
              Multi-agent coordination
            </span>
            <h1>
              Your agents ship faster when they <em>agree</em>.
            </h1>
            <p className="hero__sub">
              Consensus gives every coding agent on your team one shared claim board, one arbiter when their plans collide, and one memory they all read before they write a line.
            </p>
            <div className="hero__cta">
              <Link to={startHref} className="primary-button btn-lg">
                Get started free
                <Icon.ArrowRight />
              </Link>
              <a href="#how" className="ghost-button btn-lg">
                See how it works
              </a>
            </div>
            <p className="hero__note">No credit card. Connect your first agent in two minutes.</p>
            <div className="hero__stats">
              <div className="hero__stat">
                <b>MCP</b>
                <span>drop-in for Claude Code, Cursor, Windsurf</span>
              </div>
              <div className="hero__stat">
                <b>3 verdicts</b>
                <span>proceed, proceed with context, wait</span>
              </div>
              <div className="hero__stat">
                <b>5 kinds</b>
                <span>of shared memory</span>
              </div>
            </div>
          </div>
          <div className="hero__art">
            <img src={heroArt} alt="Two agents claim overlapping work; Consensus opens a conflict and writes the ruling to shared memory." width={640} height={470} />
          </div>
        </div>
      </section>

      <section className="section" id="how">
        <div className="wrap">
          <div className="section__head section__head--center">
            <span className="section__kicker">How it works</span>
            <h2>Three steps between "agents everywhere" and "agents that agree"</h2>
            <p>Consensus sits between your agents and your repository. It never writes code. It decides who gets to.</p>
          </div>
          <div className="steps">
            <div className="step">
              <div className="step__n">1</div>
              <h3>Connect each agent</h3>
              <p>
                Create a key in Settings and register the MCP server with <code>claude mcp add</code>, or install the Claude Code plugin. Every agent that holds a key joins the same board.
              </p>
            </div>
            <div className="step">
              <div className="step__n">2</div>
              <h3>Agents declare intent</h3>
              <p>
                Before touching code an agent calls <code>declare_intent</code>. One model call extracts the concepts it touches and the positions it takes; everything after that is deterministic.
              </p>
            </div>
            <div className="step">
              <div className="step__n">3</div>
              <h3>Consensus arbitrates</h3>
              <p>Overlapping plans open a conflict. You pick a side and leave a note; the ruling lands in shared memory and is applied automatically next time.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="section section--tint" id="features">
        <div className="wrap">
          <div className="section__head">
            <span className="section__kicker">Features</span>
            <h2>Built for the moment two agents want the same thing</h2>
            <p>Not a chat log and not a task board. A coordination layer with opinions about who proceeds.</p>
          </div>
          <div className="features">
            {FEATURES.map((feature) => (
              <article className="feature" key={feature.title}>
                <div className="feature__icon">{feature.icon}</div>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="pricing">
        <div className="wrap">
          <div className="section__head section__head--center">
            <span className="section__kicker">Pricing</span>
            <h2>Priced per developer, not per agent</h2>
            <p>Run as many agents as you like. You only pay for the humans arbitrating them.</p>
          </div>
          <div className="pricing">
            {PLANS.map((plan) => (
              <article className={`price-card${plan.featured ? ' price-card--featured' : ''}`} key={plan.name}>
                {plan.featured && <span className="price-card__tag">Most popular</span>}
                <h3>{plan.name}</h3>
                <div className="price-card__price">
                  <b>{plan.price}</b>
                  <span>{plan.unit}</span>
                </div>
                <p className="price-card__blurb">{plan.blurb}</p>
                <ul>
                  {plan.features.map((item) => (
                    <li key={item}>
                      <Icon.Check size={15} />
                      {item}
                    </li>
                  ))}
                </ul>
                <Link to={startHref} className={plan.featured ? 'primary-button' : 'ghost-button'}>
                  {plan.cta}
                </Link>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section--tint" id="start">
        <div className="wrap">
          <div className="gs-grid">
            <div>
              <div className="section__head" style={{ marginBottom: 32 }}>
                <span className="section__kicker">Getting started</span>
                <h2>From signed up to first claim in one terminal</h2>
              </div>
              <ol className="gs-list">
                <li>
                  <span className="gs-tick">1</span>
                  <div>
                    <b>Create your organisation</b>
                    <p>Sign in with GitHub, name it, invite the developers who will arbitrate.</p>
                  </div>
                </li>
                <li>
                  <span className="gs-tick">2</span>
                  <div>
                    <b>Add a team and issue a key</b>
                    <p>
                      A team maps to one repository. Settings gives you a <code>csk_</code> key, shown once.
                    </p>
                  </div>
                </li>
                <li>
                  <span className="gs-tick">3</span>
                  <div>
                    <b>Point your agents at the MCP server</b>
                    <p>One command per machine. The agent starts declaring on its own.</p>
                  </div>
                </li>
                <li>
                  <span className="gs-tick">4</span>
                  <div>
                    <b>Watch the board</b>
                    <p>Open the dashboard and arbitrate the first conflict that fires.</p>
                  </div>
                </li>
              </ol>
            </div>
            <div className="codeblock">
              <div className="codeblock__bar">
                <span className="codeblock__dot" />
                <span className="codeblock__dot" />
                <span className="codeblock__dot" />
                <span className="codeblock__name">~/acme/checkout-api</span>
              </div>
              <pre>
                <code>
                  <span className="c"># register the Consensus MCP server</span>
                  {'\n'}
                  <span className="k">claude</span> mcp add --transport http consensus \{'\n'}
                  {'  '}
                  <span className="s">{MCP_URL}</span> \{'\n'}
                  {'  '}--header <span className="s">"Authorization: Bearer csk_..."</span>
                  {'\n\n'}
                  <span className="c"># the agent now declares before it writes</span>
                  {'\n'}
                  <span className="k">&gt;</span> declare_intent(
                  {'\n'}
                  {'    '}agent_name=<span className="s">"Atlas"</span>,
                  {'\n'}
                  {'    '}plan_text=<span className="s">"Add idempotency keys to POST /charge…"</span>,
                  {'\n'}
                  {'    '}branch=<span className="s">"feat/idempotent-charge"</span>
                  {'\n'}
                  {'  '})
                  {'\n'}
                  <span className="c">{'  '}✓ verdict: proceed · 0 conflicts</span>
                </code>
              </pre>
            </div>
          </div>
        </div>
      </section>

      <section className="cta-band">
        <div className="wrap">
          <h2>Stop refereeing your agents by hand.</h2>
          <p>Set up an organisation, add your first team and let Consensus tell you the moment two plans collide.</p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link to={startHref} className="primary-button btn-lg">
              Get started free
              <Icon.ArrowRight />
            </Link>
            <Link to="/signin" className="ghost-button btn-lg">
              Sign in
            </Link>
          </div>
        </div>
      </section>

      <footer>
        <div className="wrap">
          <div className="footer__grid">
            <div className="footer__about">
              <span className="brand">
                <span className="brand__mark">
                  <Icon.Logo />
                </span>
                Consensus
              </span>
              <p>The coordination layer for teams whose coding agents outnumber their developers.</p>
            </div>
            <div className="footer__col">
              <h4>Product</h4>
              <a href="#features">Features</a>
              <a href="#pricing">Pricing</a>
              <a href="#how">How it works</a>
            </div>
            <div className="footer__col">
              <h4>Developers</h4>
              <a href="#start">Quickstart</a>
              <a href="/docs">REST API</a>
              <a href="https://github.com/masterblaster14/Consensus">Source</a>
            </div>
            <div className="footer__col">
              <h4>Company</h4>
              <a href="#start">About</a>
              <a href="#start">Privacy</a>
              <a href="#start">Terms</a>
            </div>
          </div>
          <div className="footer__base">
            <span>© {new Date().getFullYear()} Consensus. MIT licensed.</span>
          </div>
        </div>
      </footer>
    </main>
  )
}
