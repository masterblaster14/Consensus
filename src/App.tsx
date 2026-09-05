import { useState, useRef, useEffect } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Plus,
  Users,
  UserPlus,
  UserMinus,
  FolderGit2,
  ShieldCheck,
  Bot,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  LogOut,
  Copy,
  Eye,
  EyeOff,
  Link,
  Building2,
  Trash2,
  Globe,
  Zap,
  Lock,
  GitBranch,
  Menu,
  X,
  LayoutDashboard,
} from "lucide-react";
import "./App.css";


/* ══════════════════════════════════════════════════
   TYPES
══════════════════════════════════════════════════ */

type AppState  = "landing" | "onboarding" | "join-team" | "app";
type UserRole  = "admin" | "employee";
type DropdownLevel = "closed" | "root" | "manage-teams" | "manage-members";
type AdminPage =
  | "dashboard" | "add-team" | "delete-team"
  | "shift-domain" | "manage-members"
  | "add-members" | "restrict-members" | "delete-members";
type EmpPage = "dashboard" | "team-detail";

interface Team {
  id: string;
  name: string;
  secret: string;
  description: string;
  memberCount: number;
  createdAt: string;
}

interface OrgMember {
  id: string;
  name: string;
  email: string;
  initials: string;
  teamIds: string[];
  restricted: boolean;
}


/* ══════════════════════════════════════════════════
   UTILS
══════════════════════════════════════════════════ */

const genTeamId = (name: string) =>
  `${name.toLowerCase().replace(/\s+/g, "").slice(0, 4)}-${Math.random().toString(36).slice(2, 7)}`;

const genSecret = () =>
  [0, 0, 0].map(() => Math.random().toString(36).slice(2, 7)).join("-");

const genToken = () => Math.random().toString(36).slice(2, 14);


/* ══════════════════════════════════════════════════
   LOGO MARK
══════════════════════════════════════════════════ */

function ConsensusLogo() {
  return (
    <div className="logo-mark">
      <div className="hex h1" /><div className="hex h2" />
      <div className="hex h3" /><div className="hex h4" />
      <div className="hex h5" />
    </div>
  );
}


/* ══════════════════════════════════════════════════
   ROOT APP
══════════════════════════════════════════════════ */

export default function App() {
  const [appState,  setAppState]  = useState<AppState>("landing");
  const [role,      setRole]      = useState<UserRole | null>(null);
  const [orgName,   setOrgName]   = useState("");
  const [userName,  setUserName]  = useState("");
  const [teams,     setTeams]     = useState<Team[]>([]);
  const [myTeamIds, setMyTeamIds] = useState<string[]>([]);
  const [inviteToken]             = useState(genToken);
  const [adminPage, setAdminPage] = useState<AdminPage>("dashboard");
  const [empPage,   setEmpPage]   = useState<EmpPage>("dashboard");
  const [selTeamId, setSelTeamId] = useState<string | null>(null);
  const [members,   setMembers]   = useState<OrgMember[]>([
    { id: "m1", name: "Rahul Kumar",  email: "rahul@example.com",  initials: "RK", teamIds: [], restricted: false },
    { id: "m2", name: "Nisha Singh",  email: "nisha@example.com",  initials: "NS", teamIds: [], restricted: false },
  ]);

  /* handlers */
  const createOrg = (org: string, uName: string) => {
    setOrgName(org); setUserName(uName);
    setRole("admin"); setAppState("app"); setAdminPage("dashboard");
  };
  const joinOrg = () => {
    setOrgName("Acme Engineering"); setRole("employee"); setAppState("join-team");
  };
  const joinTeam = (tid: string, sec: string): boolean => {
    const t = teams.find(t => t.id === tid.trim() && t.secret === sec.trim());
    if (!t) return false;
    setMyTeamIds(p => (p.includes(t.id) ? p : [...p, t.id]));
    setAppState("app"); setEmpPage("dashboard");
    return true;
  };
  const skipJoin = () => { setAppState("app"); setEmpPage("dashboard"); };

  const createTeam = (name: string, desc: string): Team => {
    const t: Team = {
      id: genTeamId(name), name, secret: genSecret(), description: desc,
      memberCount: 0,
      createdAt: new Date().toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }),
    };
    setTeams(p => [...p, t]);
    return t;
  };
  const deleteTeam = (id: string) => {
    setTeams(p => p.filter(t => t.id !== id));
    setMyTeamIds(p => p.filter(x => x !== id));
  };
  const addMember = (name: string, email: string, teamId: string) => {
    const initials = name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
    setMembers(p => [...p, { id: `m${Date.now()}`, name, email, initials, teamIds: teamId ? [teamId] : [], restricted: false }]);
    if (teamId) setTeams(p => p.map(t => t.id === teamId ? { ...t, memberCount: t.memberCount + 1 } : t));
  };
  const deleteMember  = (id: string)  => setMembers(p => p.filter(m => m.id !== id));
  const toggleRestrict = (id: string) => setMembers(p => p.map(m => m.id === id ? { ...m, restricted: !m.restricted } : m));
  const signOut = () => {
    setAppState("landing"); setRole(null); setOrgName(""); setUserName("");
    setAdminPage("dashboard"); setEmpPage("dashboard");
  };
  const adminNav  = (p: AdminPage) => setAdminPage(p);
  const teamClick = (id: string)   => { setSelTeamId(id); setEmpPage("team-detail"); };

  const initials = userName ? userName.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2) : "ME";
  const myTeams  = teams.filter(t => myTeamIds.includes(t.id));

  return (
    <>
      <TopNav
        appState={appState} role={role} orgName={orgName}
        userName={userName} initials={initials}
        onGetStarted={() => setAppState("onboarding")}
        onSignIn={() => setAppState("onboarding")}
        onSignOut={signOut} onAdminNav={adminNav}
      />

      <main className="page-root">
        {appState === "landing"   && <LandingPage onGetStarted={() => setAppState("onboarding")} />}
        {appState === "onboarding" && (
          <OnboardingFlow
            onCreateOrg={createOrg} onJoinOrg={joinOrg}
            onBack={() => setAppState("landing")}
          />
        )}
        {appState === "join-team" && (
          <JoinTeamScreen orgName={orgName} teams={teams} onJoin={joinTeam} onSkip={skipJoin} />
        )}
        {appState === "app" && role === "admin" && (
          <AdminContent
            page={adminPage} orgName={orgName} userName={userName}
            teams={teams} members={members} inviteToken={inviteToken}
            onCreateTeam={createTeam} onDeleteTeam={deleteTeam}
            onAddMember={addMember} onDeleteMember={deleteMember}
            onToggleRestrict={toggleRestrict} onNavigate={adminNav}
          />
        )}
        {appState === "app" && role === "employee" && (
          <EmployeeContent
            myTeams={myTeams} page={empPage} selTeamId={selTeamId}
            onTeamClick={teamClick} onBack={() => setEmpPage("dashboard")}
          />
        )}
      </main>
    </>
  );
}


/* ══════════════════════════════════════════════════
   TOP NAV
══════════════════════════════════════════════════ */

function TopNav({
  appState, role, orgName, userName, initials,
  onGetStarted, onSignIn, onSignOut, onAdminNav,
}: {
  appState: AppState; role: UserRole | null; orgName: string;
  userName: string; initials: string;
  onGetStarted: () => void; onSignIn: () => void;
  onSignOut: () => void; onAdminNav: (p: AdminPage) => void;
}) {
  const [ddLevel,     setDdLevel]     = useState<DropdownLevel>("closed");
  const [mobileOpen,  setMobileOpen]  = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const isLoggedIn = appState === "app";

  /* close on outside click */
  useEffect(() => {
    const fn = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setDdLevel("closed");
      }
    };
    document.addEventListener("mousedown", fn);
    return () => document.removeEventListener("mousedown", fn);
  }, []);

  const pick = (fn: () => void) => { setDdLevel("closed"); setMobileOpen(false); fn(); };
  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
    setMobileOpen(false);
  };

  return (
    <header className="topnav">
      {/* Logo */}
      <div className="topnav-logo" onClick={() => { if (!isLoggedIn) window.scrollTo({ top: 0, behavior: "smooth" }); }}>
        <ConsensusLogo />
        <span className="topnav-brand">CONSENSUS</span>
      </div>

      {/* Centre links */}
      <nav className="topnav-links">
        {(["pricing", "how-it-works", "features"] as const).map(id => (
          <button key={id} onClick={() => scrollTo(id)}>
            {id === "how-it-works" ? "How it Works" : id.charAt(0).toUpperCase() + id.slice(1)}
          </button>
        ))}
        <button onClick={() => scrollTo("getting-started")}>Getting Started</button>
      </nav>

      {/* Right */}
      <div className="topnav-right">
        {!isLoggedIn ? (
          <>
            <button className="topnav-signin" onClick={onSignIn}>Sign In</button>
            <button className="primary-button topnav-cta" onClick={onGetStarted}>
              Get Started <ArrowRight size={14} />
            </button>
          </>
        ) : (
          <div className="account-wrap" ref={wrapRef}>
            {/* Trigger */}
            <button
              className={`account-trigger${ddLevel !== "closed" ? " open" : ""}`}
              onClick={() => setDdLevel(ddLevel === "closed" ? "root" : "closed")}
            >
              <div className="acc-avatar">{initials}</div>
              <div className="acc-info">
                <span>{userName || "You"}</span>
                <small>{role === "admin" ? "Admin" : "Member"} · {orgName}</small>
              </div>
              <ChevronDown size={13} className={ddLevel !== "closed" ? "chev-open" : ""} />
            </button>

            {/* Dropdown */}
            {ddLevel !== "closed" && (
              <div className="account-dd">
                {/* User header */}
                <div className="dd-head">
                  <div className="dd-head-avatar">{initials}</div>
                  <div>
                    <strong>{userName || "You"}</strong>
                    <span>{role === "admin" ? "Admin" : "Member"}</span>
                    <small>{orgName}</small>
                  </div>
                </div>
                <div className="dd-sep" />

                {/* ROOT */}
                {ddLevel === "root" && <>
                  <button className="dd-item" onClick={() => pick(() => onAdminNav("dashboard"))}>
                    <LayoutDashboard size={14} /> Dashboard
                  </button>
                  {role === "admin" && (
                    <button className="dd-item dd-has-sub" onClick={() => setDdLevel("manage-teams")}>
                      <Users size={14} /> Manage Teams <ChevronRight size={12} className="dd-chev" />
                    </button>
                  )}
                  <div className="dd-sep" />
                  <button className="dd-item dd-danger" onClick={() => pick(onSignOut)}>
                    <LogOut size={14} /> Sign Out
                  </button>
                </>}

                {/* MANAGE TEAMS */}
                {ddLevel === "manage-teams" && <>
                  <button className="dd-back" onClick={() => setDdLevel("root")}>
                    <ChevronLeft size={13} /> Back
                  </button>
                  <div className="dd-level-label">MANAGE TEAMS</div>
                  <button className="dd-item dd-has-sub" onClick={() => setDdLevel("manage-members")}>
                    <Users size={14} /> Manage Team Members <ChevronRight size={12} className="dd-chev" />
                  </button>
                  <div className="dd-sep" />
                  <button className="dd-item" onClick={() => pick(() => onAdminNav("add-team"))}>
                    <Plus size={14} /> Add Teams
                  </button>
                  <button className="dd-item dd-danger" onClick={() => pick(() => onAdminNav("delete-team"))}>
                    <Trash2 size={14} /> Delete Teams
                  </button>
                  <button className="dd-item" onClick={() => pick(() => onAdminNav("shift-domain"))}>
                    <Globe size={14} /> Shift Team Domain
                  </button>
                </>}

                {/* MANAGE MEMBERS */}
                {ddLevel === "manage-members" && <>
                  <button className="dd-back" onClick={() => setDdLevel("manage-teams")}>
                    <ChevronLeft size={13} /> Back
                  </button>
                  <div className="dd-level-label">TEAM MEMBERS</div>
                  <button className="dd-item" onClick={() => pick(() => onAdminNav("add-members"))}>
                    <UserPlus size={14} /> Add Members
                  </button>
                  <button className="dd-item" onClick={() => pick(() => onAdminNav("restrict-members"))}>
                    <Lock size={14} /> Restrict Members
                  </button>
                  <button className="dd-item dd-danger" onClick={() => pick(() => onAdminNav("delete-members"))}>
                    <UserMinus size={14} /> Delete Members
                  </button>
                </>}
              </div>
            )}
          </div>
        )}

        {/* Mobile hamburger */}
        <button className="mob-toggle" onClick={() => setMobileOpen(!mobileOpen)}>
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="mob-menu">
          <button onClick={() => scrollTo("pricing")}>Pricing</button>
          <button onClick={() => scrollTo("how-it-works")}>How it Works</button>
          <button onClick={() => scrollTo("features")}>Features</button>
          <button onClick={() => scrollTo("getting-started")}>Getting Started</button>
          {!isLoggedIn && <>
            <button className="topnav-signin" onClick={() => pick(onSignIn)}>Sign In</button>
            <button className="primary-button" onClick={() => pick(onGetStarted)}>Get Started</button>
          </>}
        </div>
      )}
    </header>
  );
}


/* ══════════════════════════════════════════════════
   LANDING PAGE
══════════════════════════════════════════════════ */

function LandingPage({ onGetStarted }: { onGetStarted: () => void }) {
  return (
    <div className="landing">

      {/* ── HERO ──────────────────────────────── */}
      <section className="hero-section">
        <div className="hero-content">
          <div className="hero-badge">
            <Zap size={11} /> AI Coordination Layer for Engineering Teams
          </div>
          <h1 className="hero-title">
            Where Your AI Agents<br />
            <span className="hero-accent">Find Consensus</span>
          </h1>
          <p className="hero-desc">
            Stop context conflicts. Deploy AI agents that coordinate, share memory,
            and escalate decisions — so your team ships faster without stepping on each other.
          </p>
          <div className="hero-btns">
            <button className="primary-button hero-primary" onClick={onGetStarted}>
              Start Building Free <ArrowRight size={15} />
            </button>
            <button className="secondary-button" onClick={() => document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" })}>
              See How It Works
            </button>
          </div>
          <div className="hero-stats-row">
            <div className="hero-stat"><strong>10×</strong><span>fewer conflicts</span></div>
            <div className="hero-stat-sep" />
            <div className="hero-stat"><strong>Real-time</strong><span>coordination</span></div>
            <div className="hero-stat-sep" />
            <div className="hero-stat"><strong>GitHub</strong><span>native</span></div>
          </div>
        </div>

        {/* Visual */}
        <div className="hero-visual">
          <div className="hero-hub">
            <div className="hub-ring r1" /><div className="hub-ring r2" /><div className="hub-ring r3" />
            <div className="hub-core"><Bot size={28} /></div>
          </div>
          <div className="hero-cards">
            <div className="hero-card">
              <div className="hc-dot green" />
              <div><strong>Agent Alpha</strong><span>Implementing JWT auth</span></div>
              <span className="hc-badge working">Working</span>
            </div>
            <div className="hero-card">
              <div className="hc-dot orange" />
              <div><strong>Conflict Detected</strong><span>2 agents modifying same file</span></div>
              <span className="hc-badge conflict">Conflict</span>
            </div>
            <div className="hero-card">
              <div className="hc-dot blue" />
              <div><strong>Decision Logged</strong><span>Shared memory updated</span></div>
              <span className="hc-badge resolved">Resolved</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ──────────────────────── */}
      <section id="how-it-works" className="lp-section hiw-section">
        <div className="lp-inner">
          <div className="lp-label">HOW IT WORKS</div>
          <h2 className="lp-title">Ship faster, together</h2>
          <p className="lp-sub">Three steps to eliminate AI coordination chaos in your team.</p>
          <div className="steps-grid">
            {[
              { n: "01", icon: <GitBranch size={22} />, title: "Connect", desc: "Link your GitHub repositories and invite your engineering team. Takes under 2 minutes." },
              { n: "02", icon: <Bot size={22} />, title: "Deploy", desc: "Each developer spawns AI agents that claim tasks, share context, and coordinate in real time." },
              { n: "03", icon: <CheckCircle2 size={22} />, title: "Arbitrate", desc: "When agents conflict, you make the call. The decision is recorded in shared memory for all agents." },
            ].map(s => (
              <div key={s.n} className="step-card">
                <div className="step-n">{s.n}</div>
                <div className="step-icon">{s.icon}</div>
                <h3>{s.title}</h3>
                <p>{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FEATURES ──────────────────────────── */}
      <section id="features" className="lp-section feat-section">
        <div className="lp-inner">
          <div className="lp-label">FEATURES</div>
          <h2 className="lp-title">Everything your team needs</h2>
          <p className="lp-sub">Built for engineering teams that move fast and ship nothing broken.</p>
          <div className="feat-grid">
            {[
              { icon: <Bot size={20} />,          title: "Agent Coordination Board",  desc: "Real-time view of every agent, task claim, and status across your entire repository." },
              { icon: <AlertTriangle size={20} />, title: "Conflict Resolution",       desc: "When two agents clash, humans arbitrate. All decisions are logged permanently." },
              { icon: <CheckCircle2 size={20} />, title: "Shared Team Memory",        desc: "Rules, decisions, and context shared across every agent working in a project." },
              { icon: <Users size={20} />,         title: "Team Management",           desc: "Admin creates teams, generates credentials, and employees join their assigned teams." },
              { icon: <Lock size={20} />,          title: "Role-based Access",         desc: "Admins control everything. Members see and act only within their own teams." },
              { icon: <FolderGit2 size={20} />,   title: "GitHub Native",             desc: "Connect repos in one click. AI agents read code and can open pull requests directly." },
            ].map(f => (
              <div key={f.title} className="feat-card">
                <div className="feat-icon">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── PRICING ───────────────────────────── */}
      <section id="pricing" className="lp-section price-section">
        <div className="lp-inner">
          <div className="lp-label">PRICING</div>
          <h2 className="lp-title">Simple, transparent pricing</h2>
          <p className="lp-sub">Start free. Scale when your team is ready.</p>
          <div className="price-grid">
            <PricingCard
              tier="Starter" price="Free" period="forever"
              desc="Perfect for solo developers exploring AI-assisted development."
              features={["1 repository", "3 AI agents", "Basic arbitration", "Shared memory", "Community support"]}
              cta="Start Free" onCta={onGetStarted} highlighted={false}
            />
            <PricingCard
              tier="Pro" price="$29" period="/ month"
              desc="For small teams shipping production software with AI agents."
              features={["Up to 10 repositories", "Unlimited AI agents", "Team management", "Invite links & credentials", "Priority support", "Analytics dashboard"]}
              cta="Start Pro Trial" onCta={onGetStarted} highlighted={true}
            />
            <PricingCard
              tier="Enterprise" price="Custom" period=""
              desc="For large organisations with advanced compliance and scale needs."
              features={["Unlimited everything", "SSO & SAML", "Custom SLAs", "Dedicated support", "Audit logs", "On-premise option"]}
              cta="Contact Sales" onCta={() => {}} highlighted={false}
            />
          </div>
        </div>
      </section>

      {/* ── GETTING STARTED ───────────────────── */}
      <section id="getting-started" className="lp-section gs-section">
        <div className="gs-inner">
          <h2>Ready to eliminate context conflicts?</h2>
          <p>Join engineering teams already shipping faster with Consensus.</p>
          <button className="primary-button gs-cta" onClick={onGetStarted}>
            Get Started Free <ArrowRight size={16} />
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="lp-footer">
        <div className="footer-logo">
          <ConsensusLogo /><span>CONSENSUS</span>
        </div>
        <span>© 2026 Consensus. All rights reserved.</span>
        <div className="footer-links">
          <a href="#">Privacy</a><a href="#">Terms</a><a href="#">GitHub</a>
        </div>
      </footer>

    </div>
  );
}

function PricingCard({
  tier, price, period, desc, features, cta, onCta, highlighted,
}: {
  tier: string; price: string; period: string; desc: string;
  features: string[]; cta: string; onCta: () => void; highlighted: boolean;
}) {
  return (
    <div className={`price-card${highlighted ? " price-hl" : ""}`}>
      {highlighted && <div className="price-badge">Most Popular</div>}
      <div className="price-tier">{tier}</div>
      <div className="price-amount-row">
        <span className="price-num">{price}</span>
        {period && <span className="price-per">{period}</span>}
      </div>
      <p className="price-desc">{desc}</p>
      <ul className="price-features">
        {features.map(f => (
          <li key={f}><CheckCircle2 size={13} />{f}</li>
        ))}
      </ul>
      <button
        className={highlighted ? "primary-button price-cta" : "secondary-button price-cta"}
        onClick={onCta}
      >
        {cta} {highlighted && <ArrowRight size={13} />}
      </button>
    </div>
  );
}


/* ══════════════════════════════════════════════════
   ONBOARDING FLOW
══════════════════════════════════════════════════ */

function OnboardingFlow({
  onCreateOrg, onJoinOrg, onBack,
}: {
  onCreateOrg: (org: string, name: string) => void;
  onJoinOrg: () => void;
  onBack: () => void;
}) {
  const [mode,      setMode]     = useState<"choose" | "create" | "join">("choose");
  const [orgName,   setOrgName]  = useState("");
  const [myName,    setMyName]   = useState("");
  const [inviteVal, setInvLink]  = useState("");

  if (mode === "create") return (
    <div className="ob-wrap">
      <div className="ob-card">
        <button className="ob-back" onClick={() => setMode("choose")}><ChevronLeft size={14} /> Back</button>
        <div className="ob-logo"><ConsensusLogo /><span className="topnav-brand">CONSENSUS</span></div>
        <h2>Create your Organisation</h2>
        <p className="ob-sub">You'll be the Admin and can invite your team from the Members page.</p>
        <div className="ob-form">
          <label>Your Name</label>
          <input placeholder="e.g. Aarushi Manot" value={myName} onChange={e => setMyName(e.target.value)} />
          <label>Organisation Name</label>
          <input placeholder="e.g. Acme Engineering" value={orgName}
            onChange={e => setOrgName(e.target.value)}
            onKeyDown={e => e.key === "Enter" && orgName.trim() && myName.trim() && onCreateOrg(orgName.trim(), myName.trim())}
            autoFocus
          />
          <button className="primary-button ob-cta"
            disabled={!orgName.trim() || !myName.trim()}
            onClick={() => onCreateOrg(orgName.trim(), myName.trim())}>
            Create Organisation <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  );

  if (mode === "join") return (
    <div className="ob-wrap">
      <div className="ob-card">
        <button className="ob-back" onClick={() => setMode("choose")}><ChevronLeft size={14} /> Back</button>
        <div className="ob-logo"><ConsensusLogo /><span className="topnav-brand">CONSENSUS</span></div>
        <h2>Join an Organisation</h2>
        <p className="ob-sub">Paste the invite link your Admin shared with you. You'll then enter your team credentials.</p>
        <div className="ob-form">
          <label>Invite Link</label>
          <input placeholder="https://consensus.ai/join?org=...&token=..." value={inviteVal}
            onChange={e => setInvLink(e.target.value)} autoFocus />
          <button className="primary-button ob-cta" disabled={!inviteVal.trim()} onClick={onJoinOrg}>
            Join Organisation <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="ob-wrap">
      <div className="ob-card">
        <button className="ob-back" onClick={onBack}><ChevronLeft size={14} /> Back to home</button>
        <div className="ob-logo"><ConsensusLogo /><div><span className="topnav-brand">CONSENSUS</span><div className="ob-tagline">AI COLLABORATION LAYER</div></div></div>
        <h1 className="ob-title">Welcome to Consensus</h1>
        <p className="ob-sub">The AI coordination layer for your engineering organisation.</p>
        <div className="ob-choices">
          <button className="ob-choice" onClick={() => setMode("create")}>
            <div className="ob-choice-icon"><Building2 size={24} /></div>
            <div><strong>Create Organisation</strong><span>Set up a new workspace. You'll be the Admin.</span></div>
            <ChevronRight size={16} className="ob-chev" />
          </button>
          <button className="ob-choice" onClick={() => setMode("join")}>
            <div className="ob-choice-icon secondary"><UserPlus size={24} /></div>
            <div><strong>Join Organisation</strong><span>Use an invite link from your Admin to join.</span></div>
            <ChevronRight size={16} className="ob-chev" />
          </button>
        </div>
      </div>
    </div>
  );
}


/* ══════════════════════════════════════════════════
   JOIN TEAM SCREEN
══════════════════════════════════════════════════ */

function JoinTeamScreen({
  orgName, teams, onJoin, onSkip,
}: {
  orgName: string; teams: Team[];
  onJoin: (id: string, secret: string) => boolean;
  onSkip: () => void;
}) {
  const [tid,    setTid]    = useState("");
  const [sec,    setSec]    = useState("");
  const [show,   setShow]   = useState(false);
  const [err,    setErr]    = useState("");

  const attempt = () => {
    const ok = onJoin(tid, sec);
    if (!ok) setErr("Invalid Team ID or Secret — check with your Admin.");
  };

  return (
    <div className="ob-wrap">
      <div className="ob-card">
        <div className="ob-logo"><ConsensusLogo /><span className="topnav-brand">CONSENSUS</span></div>
        <div className="joined-badge"><CheckCircle2 size={13} /> Joined {orgName}</div>
        <h2>Join Your Team</h2>
        <p className="ob-sub">
          Enter the Team ID and Secret your Admin shared with you.
          {teams.length === 0 && <span className="ob-note"> Your Admin hasn't created any teams yet — ask them to do that first.</span>}
        </p>
        <div className="ob-form">
          <label>Team ID</label>
          <input placeholder="e.g. fron-abc12" value={tid}
            onChange={e => { setTid(e.target.value); setErr(""); }} />
          <label>Team Secret</label>
          <div className="sec-wrap">
            <input type={show ? "text" : "password"} placeholder="e.g. abc12-def34-ghi56"
              value={sec} onChange={e => { setSec(e.target.value); setErr(""); }} />
            <button type="button" className="sec-toggle" onClick={() => setShow(!show)}>
              {show ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          {err && <div className="form-err">{err}</div>}
          <button className="primary-button ob-cta" disabled={!tid.trim() || !sec.trim()} onClick={attempt}>
            Join Team <ArrowRight size={15} />
          </button>
          <button className="skip-btn" onClick={onSkip}>Skip for now — join a team later</button>
        </div>
      </div>
    </div>
  );
}


/* ══════════════════════════════════════════════════
   ADMIN CONTENT ROUTER
══════════════════════════════════════════════════ */

function AdminContent({
  page, orgName, userName, teams, members, inviteToken,
  onCreateTeam, onDeleteTeam, onAddMember, onDeleteMember, onToggleRestrict, onNavigate,
}: {
  page: AdminPage; orgName: string; userName: string;
  teams: Team[]; members: OrgMember[]; inviteToken: string;
  onCreateTeam: (n: string, d: string) => Team;
  onDeleteTeam: (id: string) => void;
  onAddMember: (n: string, e: string, tid: string) => void;
  onDeleteMember: (id: string) => void;
  onToggleRestrict: (id: string) => void;
  onNavigate: (p: AdminPage) => void;
}) {
  return (
    <div className="admin-root">
      {page === "dashboard"        && <AdminDashboard orgName={orgName} userName={userName} teams={teams} members={members} onNavigate={onNavigate} />}
      {page === "add-team"         && <AddTeamPage teams={teams} onCreateTeam={onCreateTeam} />}
      {page === "delete-team"      && <DeleteTeamPage teams={teams} onDeleteTeam={onDeleteTeam} />}
      {page === "shift-domain"     && <ShiftDomainPage teams={teams} />}
      {page === "manage-members"   && <ManageMembersPage members={members} teams={teams} inviteToken={inviteToken} orgName={orgName} />}
      {page === "add-members"      && <AddMembersPage teams={teams} onAddMember={onAddMember} />}
      {page === "restrict-members" && <RestrictMembersPage members={members} onToggleRestrict={onToggleRestrict} />}
      {page === "delete-members"   && <DeleteMembersPage members={members} onDeleteMember={onDeleteMember} />}
    </div>
  );
}


/* ─── Admin: Dashboard ─────────────────────── */

function AdminDashboard({ orgName, userName, teams, members, onNavigate }: {
  orgName: string; userName: string; teams: Team[];
  members: OrgMember[]; onNavigate: (p: AdminPage) => void;
}) {
  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  })();

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">ADMIN DASHBOARD</div>
          <h1>{greeting}, {userName || "Admin"}</h1>
          <p className="page-sub">Here's an overview of <strong>{orgName}</strong>.</p>
        </div>
        <button className="primary-button" onClick={() => onNavigate("add-team")}>
          <Plus size={16} /> Create Team
        </button>
      </div>

      {/* Stats */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-icon"><Users size={20} /></div>
          <div><span className="stat-num">{teams.length}</span><span className="stat-label">Teams</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><UserPlus size={20} /></div>
          <div><span className="stat-num">{members.length}</span><span className="stat-label">Members</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><FolderGit2 size={20} /></div>
          <div><span className="stat-num">2</span><span className="stat-label">Repositories</span></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><Bot size={20} /></div>
          <div><span className="stat-num">6</span><span className="stat-label">Active Agents</span></div>
        </div>
      </div>

      {/* Teams section */}
      <div className="admin-section">
        <div className="admin-section-head">
          <h2>Teams</h2>
          <button className="secondary-button sm-btn" onClick={() => onNavigate("add-team")}>
            <Plus size={13} /> Add Team
          </button>
        </div>
        {teams.length === 0 ? (
          <div className="inline-empty">
            <ShieldCheck size={28} />
            <p>No teams yet. Create your first team to generate credentials for employees.</p>
            <button className="primary-button" onClick={() => onNavigate("add-team")}>
              <Plus size={15} /> Create First Team
            </button>
          </div>
        ) : (
          <div className="admin-teams-list">
            {teams.map(t => (
              <div key={t.id} className="admin-team-row">
                <div className="atr-avatar">{t.name[0].toUpperCase()}</div>
                <div className="atr-info">
                  <strong>{t.name}</strong>
                  <span>{t.description || "No description"} · Created {t.createdAt}</span>
                </div>
                <div className="atr-members"><Users size={13} /> {t.memberCount} members</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Members section */}
      <div className="admin-section">
        <div className="admin-section-head">
          <h2>Members</h2>
          <button className="secondary-button sm-btn" onClick={() => onNavigate("add-members")}>
            <UserPlus size={13} /> Add Member
          </button>
        </div>
        <div className="admin-members-list">
          {members.map(m => (
            <div key={m.id} className="admin-member-row">
              <div className="amr-avatar">{m.initials}</div>
              <div className="amr-info">
                <strong>{m.name}</strong>
                <span>{m.email}</span>
              </div>
              {m.restricted && <span className="amr-restricted"><Lock size={11} /> Restricted</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


/* ─── Admin: Add Team ──────────────────────── */

function AddTeamPage({ teams, onCreateTeam }: {
  teams: Team[];
  onCreateTeam: (n: string, d: string) => Team;
}) {
  const [name,    setName]    = useState("");
  const [desc,    setDesc]    = useState("");
  const [created, setCreated] = useState<Team | null>(null);
  const [copied,  setCopied]  = useState<Record<string, boolean>>({});
  const [showSec, setShowSec] = useState(false);

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopied(p => ({ ...p, [key]: true }));
    setTimeout(() => setCopied(p => ({ ...p, [key]: false })), 2000);
  };

  const handleCreate = () => {
    if (!name.trim()) return;
    const t = onCreateTeam(name.trim(), desc.trim());
    setCreated(t); setName(""); setDesc(""); setShowSec(false);
  };

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">MANAGE TEAMS</div>
          <h1>Add Team</h1>
          <p className="page-sub">Create a new team. A unique ID and Secret will be generated — share them with your employees.</p>
        </div>
      </div>

      {/* Created credentials display */}
      {created && (
        <div className="cred-reveal">
          <div className="cred-reveal-header">
            <CheckCircle2 size={18} />
            <div>
              <strong>Team "{created.name}" created!</strong>
              <span>Share these credentials with your team members. The secret is shown only once.</span>
            </div>
          </div>
          <div className="cred-rows">
            <div className="cred-row">
              <span className="cr-label">Team ID</span>
              <div className="cr-val">
                <code>{created.id}</code>
                <button className="cr-copy" onClick={() => copy(created.id, "id")}>
                  {copied["id"] ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                </button>
              </div>
            </div>
            <div className="cred-row">
              <span className="cr-label">Team Secret</span>
              <div className="cr-val">
                <code>{showSec ? created.secret : "•".repeat(17)}</code>
                <button className="cr-copy" onClick={() => setShowSec(!showSec)}>
                  {showSec ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
                {showSec && (
                  <button className="cr-copy" onClick={() => copy(created.secret, "sec")}>
                    {copied["sec"] ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                  </button>
                )}
              </div>
            </div>
          </div>
          <p className="cred-note">🔒 Admin-only. Never share the secret publicly.</p>
        </div>
      )}

      {/* Form */}
      <div className="page-form">
        <div className="form-row">
          <label className="form-label">Team Name</label>
          <input className="form-input" placeholder="e.g. Frontend Team"
            value={name} onChange={e => setName(e.target.value)} autoFocus />
        </div>
        <div className="form-row">
          <label className="form-label">Description <span className="optional">(optional)</span></label>
          <input className="form-input" placeholder="What does this team work on?"
            value={desc} onChange={e => setDesc(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleCreate()} />
        </div>
        <button className="primary-button" disabled={!name.trim()} onClick={handleCreate}>
          <Plus size={15} /> Create Team
        </button>
      </div>

      {/* Existing teams */}
      {teams.length > 0 && (
        <div className="admin-section">
          <div className="admin-section-head"><h2>Existing Teams</h2></div>
          <div className="admin-teams-list">
            {teams.map(t => (
              <div key={t.id} className="admin-team-row">
                <div className="atr-avatar">{t.name[0].toUpperCase()}</div>
                <div className="atr-info">
                  <strong>{t.name}</strong>
                  <span>ID: <code className="inline-code">{t.id}</code> · Created {t.createdAt}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


/* ─── Admin: Delete Team ───────────────────── */

function DeleteTeamPage({ teams, onDeleteTeam }: {
  teams: Team[];
  onDeleteTeam: (id: string) => void;
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">MANAGE TEAMS</div>
          <h1>Delete Teams</h1>
          <p className="page-sub">Permanently remove a team. This action cannot be undone.</p>
        </div>
      </div>

      {teams.length === 0 ? (
        <div className="inline-empty">
          <ShieldCheck size={28} /><p>No teams to delete.</p>
        </div>
      ) : (
        <div className="delete-list">
          {teams.map(t => (
            <div key={t.id} className="delete-item">
              <div className="di-avatar">{t.name[0].toUpperCase()}</div>
              <div className="di-info">
                <strong>{t.name}</strong>
                <span>{t.memberCount} members · Created {t.createdAt}</span>
              </div>
              {confirmId === t.id ? (
                <div className="di-confirm">
                  <span>Sure?</span>
                  <button className="danger-btn" onClick={() => { onDeleteTeam(t.id); setConfirmId(null); }}>
                    Yes, Delete
                  </button>
                  <button className="secondary-button sm-btn" onClick={() => setConfirmId(null)}>Cancel</button>
                </div>
              ) : (
                <button className="danger-btn" onClick={() => setConfirmId(t.id)}>
                  <Trash2 size={13} /> Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


/* ─── Admin: Shift Domain ──────────────────── */

function ShiftDomainPage({ teams }: { teams: Team[] }) {
  const [selId,  setSelId]  = useState("");
  const [domain, setDomain] = useState("");
  const [saved,  setSaved]  = useState(false);

  const handleSave = () => { setSaved(true); setTimeout(() => setSaved(false), 2500); };

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">MANAGE TEAMS</div>
          <h1>Shift Team Domain</h1>
          <p className="page-sub">Reassign or update the primary domain for a team.</p>
        </div>
      </div>
      <div className="page-form">
        <div className="form-row">
          <label className="form-label">Select Team</label>
          <select className="form-input form-select" value={selId} onChange={e => setSelId(e.target.value)}>
            <option value="">— Choose a team —</option>
            {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <div className="form-row">
          <label className="form-label">New Domain</label>
          <input className="form-input" placeholder="e.g. payments.acme.io" value={domain}
            onChange={e => setDomain(e.target.value)} />
        </div>
        {saved && <div className="success-msg"><CheckCircle2 size={14} /> Domain updated successfully.</div>}
        <button className="primary-button" disabled={!selId || !domain.trim()} onClick={handleSave}>
          <Globe size={15} /> Save Domain
        </button>
      </div>
    </div>
  );
}


/* ─── Admin: Manage Members overview ──────── */

function ManageMembersPage({ members, teams, inviteToken, orgName }: {
  members: OrgMember[]; teams: Team[];
  inviteToken: string; orgName: string;
}) {
  const [copied, setCopied] = useState(false);
  const url = `https://consensus.ai/join?org=${encodeURIComponent(orgName)}&token=${inviteToken}`;
  const copy = () => { navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2000); };

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">MANAGE TEAMS</div>
          <h1>Team Members</h1>
          <p className="page-sub">View, add, restrict, or remove members from your organisation.</p>
        </div>
        <button className="primary-button" onClick={copy}>
          <Link size={15} /> {copied ? "Copied!" : "Copy Invite Link"}
        </button>
      </div>

      {/* Invite banner */}
      <div className="invite-banner">
        <div className="ib-top">
          <div className="ib-icon"><Link size={17} /></div>
          <div>
            <strong>Invite Members to {orgName}</strong>
            <span>Share this link. After joining the org, employees use team credentials to access their team.</span>
          </div>
        </div>
        <div className="ib-url-row">
          <code className="ib-url">{url}</code>
          <button className="copy-lg" onClick={copy}>
            {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />} {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      </div>

      {/* Members table */}
      <div className="members-table">
        <div className="mem-row mem-header">
          <span>Member</span><span>Email</span><span>Teams</span><span>Status</span>
        </div>
        {members.map(m => (
          <div key={m.id} className="mem-row">
            <div className="mem-name">
              <div className="mem-avatar">{m.initials}</div>
              <strong>{m.name}</strong>
            </div>
            <span className="mem-email">{m.email}</span>
            <span>
              {m.teamIds.length === 0
                ? "—"
                : m.teamIds.map(tid => teams.find(t => t.id === tid)?.name || tid).join(", ")}
            </span>
            <span className={`mem-status ${m.restricted ? "restricted" : "active"}`}>
              <span />
              {m.restricted ? "Restricted" : "Active"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ─── Admin: Add Members ───────────────────── */

function AddMembersPage({ teams, onAddMember }: {
  teams: Team[];
  onAddMember: (n: string, e: string, tid: string) => void;
}) {
  const [name,   setName]  = useState("");
  const [email,  setEmail] = useState("");
  const [teamId, setTeamId]= useState("");
  const [done,   setDone]  = useState(false);

  const handleAdd = () => {
    if (!name.trim() || !email.trim()) return;
    onAddMember(name.trim(), email.trim(), teamId);
    setDone(true); setName(""); setEmail(""); setTeamId("");
    setTimeout(() => setDone(false), 2500);
  };

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">TEAM MEMBERS</div>
          <h1>Add Member</h1>
          <p className="page-sub">Add a new member to your organisation and assign them to a team.</p>
        </div>
      </div>
      <div className="page-form">
        <div className="form-row">
          <label className="form-label">Full Name</label>
          <input className="form-input" placeholder="e.g. Rahul Kumar" value={name}
            onChange={e => setName(e.target.value)} autoFocus />
        </div>
        <div className="form-row">
          <label className="form-label">Email Address</label>
          <input className="form-input" type="email" placeholder="e.g. rahul@company.com"
            value={email} onChange={e => setEmail(e.target.value)} />
        </div>
        <div className="form-row">
          <label className="form-label">Assign to Team <span className="optional">(optional)</span></label>
          <select className="form-input form-select" value={teamId} onChange={e => setTeamId(e.target.value)}>
            <option value="">— Select a team —</option>
            {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        {done && <div className="success-msg"><CheckCircle2 size={14} /> Member added successfully!</div>}
        <button className="primary-button" disabled={!name.trim() || !email.trim()} onClick={handleAdd}>
          <UserPlus size={15} /> Add Member
        </button>
      </div>
    </div>
  );
}


/* ─── Admin: Restrict Members ──────────────── */

function RestrictMembersPage({ members, onToggleRestrict }: {
  members: OrgMember[];
  onToggleRestrict: (id: string) => void;
}) {
  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">TEAM MEMBERS</div>
          <h1>Restrict Members</h1>
          <p className="page-sub">Toggle restrictions to limit a member's access within their teams.</p>
        </div>
      </div>
      <div className="delete-list">
        {members.length === 0 && (
          <div className="inline-empty"><Users size={28} /><p>No members in your organisation yet.</p></div>
        )}
        {members.map(m => (
          <div key={m.id} className="delete-item">
            <div className="di-avatar">{m.initials}</div>
            <div className="di-info">
              <strong>{m.name}</strong>
              <span>{m.email}</span>
            </div>
            <button
              className={`toggle-btn ${m.restricted ? "toggled" : ""}`}
              onClick={() => onToggleRestrict(m.id)}
            >
              <div className="toggle-thumb" />
            </button>
            <span className={`restrict-label ${m.restricted ? "on" : ""}`}>
              {m.restricted ? "Restricted" : "Active"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ─── Admin: Delete Members ────────────────── */

function DeleteMembersPage({ members, onDeleteMember }: {
  members: OrgMember[];
  onDeleteMember: (id: string) => void;
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null);

  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">TEAM MEMBERS</div>
          <h1>Delete Members</h1>
          <p className="page-sub">Permanently remove a member from your organisation.</p>
        </div>
      </div>
      <div className="delete-list">
        {members.length === 0 && (
          <div className="inline-empty"><Users size={28} /><p>No members to remove.</p></div>
        )}
        {members.map(m => (
          <div key={m.id} className="delete-item">
            <div className="di-avatar">{m.initials}</div>
            <div className="di-info">
              <strong>{m.name}</strong><span>{m.email}</span>
            </div>
            {confirmId === m.id ? (
              <div className="di-confirm">
                <span>Sure?</span>
                <button className="danger-btn" onClick={() => { onDeleteMember(m.id); setConfirmId(null); }}>
                  Yes, Remove
                </button>
                <button className="secondary-button sm-btn" onClick={() => setConfirmId(null)}>Cancel</button>
              </div>
            ) : (
              <button className="danger-btn" onClick={() => setConfirmId(m.id)}>
                <UserMinus size={13} /> Remove
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


/* ══════════════════════════════════════════════════
   EMPLOYEE CONTENT
══════════════════════════════════════════════════ */

function EmployeeContent({
  myTeams, page, selTeamId, onTeamClick, onBack,
}: {
  myTeams: Team[]; page: EmpPage; selTeamId: string | null;
  onTeamClick: (id: string) => void; onBack: () => void;
}) {
  /* Team detail placeholder */
  if (page === "team-detail") {
    const team = myTeams.find(t => t.id === selTeamId);
    return (
      <div className="page-wrap">
        <button className="ob-back inline-back" onClick={onBack}>
          <ChevronLeft size={14} /> Back to My Teams
        </button>
        <div className="page-head">
          <div>
            <div className="page-eyebrow">TEAM WORKSPACE</div>
            <h1>{team?.name ?? "Team"}</h1>
            <p className="page-sub">{team?.description || "Your team's collaboration workspace."}</p>
          </div>
        </div>
        <div className="placeholder-box">
          <div className="ph-icon"><Bot size={40} /></div>
          <h3>Workspace Coming Soon</h3>
          <p>This team's page is being built by your teammate and will be integrated here shortly.</p>
          <div className="ph-meta">
            <span><Users size={13} /> {team?.memberCount ?? 0} members</span>
            <span>Team ID: <code>{team?.id}</code></span>
          </div>
        </div>
      </div>
    );
  }

  /* Team blocks grid */
  return (
    <div className="page-wrap">
      <div className="page-head">
        <div>
          <div className="page-eyebrow">YOUR WORKSPACE</div>
          <h1>My Teams</h1>
          <p className="page-sub">Click a team to open its collaboration dashboard.</p>
        </div>
      </div>

      {myTeams.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon"><ShieldCheck size={38} /></div>
          <h3>No teams yet</h3>
          <p>You haven't joined any teams. Ask your Admin for a Team ID and Secret to get access.</p>
        </div>
      ) : (
        <div className="team-blocks">
          {myTeams.map(t => (
            <button key={t.id} className="team-block" onClick={() => onTeamClick(t.id)}>
              <div className="tb-letter">{t.name[0].toUpperCase()}</div>
              <div className="tb-name">{t.name}</div>
              {t.description && <p className="tb-desc">{t.description}</p>}
              <div className="tb-meta">
                <span><Users size={13} /> {t.memberCount} members</span>
                <span>{t.createdAt}</span>
              </div>
              <div className="tb-cta">
                Open Dashboard <ArrowRight size={14} />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}