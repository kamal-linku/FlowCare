import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowUpRight, BarChart3, Bell, Check,
  ChevronDown, Clock3, Command, LayoutDashboard, LogOut, Menu, Plus, RefreshCw,
  Search, Settings, ShieldCheck, Stethoscope, Users, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { ApiError, api } from "./api";
import type { Department, Overview, Prediction, SimulationResult, Ticket, User } from "./types";

type Page = "overview" | "queue" | "registration" | "simulation" | "analytics" | "alerts" | "staff" | "settings";
const nav: Array<{ id: Page; label: string; group: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", group: "WORKSPACE", icon: LayoutDashboard },
  { id: "queue", label: "Live queue", group: "WORKSPACE", icon: Activity },
  { id: "registration", label: "Register patient", group: "WORKSPACE", icon: Plus },
  { id: "simulation", label: "Scenario lab", group: "INTELLIGENCE", icon: BarChart3 },
  { id: "analytics", label: "Analytics", group: "INTELLIGENCE", icon: Clock3 },
  { id: "alerts", label: "Bottlenecks", group: "INTELLIGENCE", icon: AlertTriangle },
  { id: "staff", label: "Staff & departments", group: "ADMINISTRATION", icon: Users },
  { id: "settings", label: "Settings & audit", group: "ADMINISTRATION", icon: Settings },
];

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Something went wrong. Please retry.";
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState<Page>("overview");
  const [notice, setNotice] = useState("");
  const [mobileNav, setMobileNav] = useState(false);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null)).finally(() => setChecking(false));
  }, []);

  const notify = useCallback((text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice(""), 4200);
  }, []);

  if (checking) return <div className="loading-screen"><span className="loader" />Loading FlowCare</div>;
  if (!user) return <Login onLogin={setUser} notify={notify} />;
  const changePage = (next: Page) => { setPage(next); setMobileNav(false); };
  return (
    <div className="shell">
      {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); changePage("overview"); }}>
          <span className="brand-mark"><Stethoscope size={19} /></span>
          <span><strong>flowcare</strong><small>CARE OPERATIONS</small></span>
        </a>
        <div className="workspace-switch">
          <span className="hospital-mark">NH</span>
          <span><strong>Northstar Health</strong><small>Outpatient center</small></span>
          <ChevronDown size={15} />
        </div>
        <nav className="navigation" aria-label="Main navigation">
          {["WORKSPACE", "INTELLIGENCE", "ADMINISTRATION"].map((group) => (
            <section key={group} className="nav-section">
              <p className="nav-heading">{group}</p>
              {nav.filter((item) => item.group === group).map(({ id, label, icon: Icon }) => (
                <button key={id} className={`nav-link ${page === id ? "nav-active" : ""}`} onClick={() => changePage(id)}>
                  <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
                  {id === "alerts" && <span className="nav-dot" />}
                </button>
              ))}
            </section>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card"><ShieldCheck size={17} /><div><strong>Privacy-first demo</strong><small>Synthetic data workspace</small></div></div>
          <button className="profile-row" onClick={() => { api.logout(); setUser(null); }}>
            <span className="avatar">{user.display_name.split(/\s+/).map((s) => s[0]).slice(0, 2).join("").toUpperCase()}</span>
            <span className="profile-name"><strong>{user.display_name}</strong><small>{user.role}</small></span>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNav(true)}><Menu size={20} /></button>
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-sep">/</span><strong>{nav.find((item) => item.id === page)?.label}</strong></div>
          <div className="top-actions">
            <span className="live-pill"><span /> LIVE DATA</span>
            <button className="icon-button" title="Refresh dashboard" onClick={() => window.location.reload()}><RefreshCw size={16} /></button>
            <button className="icon-button" aria-label="Notifications" onClick={() => changePage("alerts")}><Bell size={17} /></button>
            <span className="top-avatar">{user.display_name[0]?.toUpperCase()}</span>
          </div>
        </header>
        <div className="content">
          {page === "overview" && <OverviewPage onNavigate={changePage} notify={notify} />}
          {page === "queue" && <QueuePage notify={notify} />}
          {page === "registration" && <RegistrationPage notify={notify} />}
          {page === "simulation" && <SimulationPage user={user} notify={notify} />}
          {page === "analytics" && <AnalyticsPage notify={notify} />}
          {page === "alerts" && <AlertsPage notify={notify} />}
          {page === "staff" && <StaffPage user={user} notify={notify} />}
          {page === "settings" && <SettingsPage user={user} notify={notify} />}
        </div>
      </main>
      {notice && <div className="toast" role="status"><Check size={17} />{notice}<button onClick={() => setNotice("")} aria-label="Dismiss"><X size={16} /></button></div>}
    </div>
  );
}

function Login({ onLogin, notify }: { onLogin: (user: User) => void; notify: (text: string) => void }) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "signin") {
        const user = await api.login(email, password);
        onLogin(user);
        notify("Signed in to FlowCare.");
      } else {
        const user = await api.signup({
          email,
          password,
          display_name: displayName.trim(),
        });
        onLogin(user);
        notify(`Account created. Welcome, ${user.display_name}!`);
      }
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <section className="login-visual">
        <div className="login-brand">
          <span className="brand-mark"><Stethoscope size={20} /></span>
          <strong>flowcare</strong>
        </div>
        <div className="visual-content">
          <span className="eyebrow">HOSPITAL OPERATIONS INTELLIGENCE</span>
          <h1>Make every<br />minute matter.</h1>
          <p>One clearer view of your outpatient flow. Understand the queue, anticipate demand, and make better-informed decisions.</p>
          <div className="visual-quote">
            <span>“</span>
            <p>Better visibility is the first step toward a better patient experience.</p>
          </div>
        </div>
        <small className="visual-foot">FLOWCARE · OPERATIONS SUITE · 2026</small>
      </section>

      <section className="login-panel">
        <form className="login-form" onSubmit={submit}>
          <div className="login-icon"><ShieldCheck size={22} /></div>

          <div className="auth-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signin"}
              className={`auth-tab ${mode === "signin" ? "auth-tab-active" : ""}`}
              onClick={() => { setMode("signin"); setError(""); }}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "signup"}
              className={`auth-tab ${mode === "signup" ? "auth-tab-active" : ""}`}
              onClick={() => { setMode("signup"); setError(""); }}
            >
              Sign up
            </button>
          </div>

          <span className="eyebrow">{mode === "signin" ? "WELCOME BACK" : "NEW ACCOUNT"}</span>
          <h2>{mode === "signin" ? "Sign in to FlowCare" : "Create an account"}</h2>
          <p className="muted">
            {mode === "signin"
              ? "Use your staff account to access the operations workspace."
              : "Create your account to access the workspace as a receptionist."}
          </p>

          {mode === "signup" && (
            <>
              <label>
                Full name
                <input
                  type="text"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                  placeholder="e.g. Dr. Jane Smith or Kamal Behera"
                />
              </label>

            </>
          )}

          <label>
            Email address
            <input
              autoComplete="username"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              placeholder="you@hospital.org"
            />
          </label>

          <label>
            Password
            <input
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={mode === "signup" ? 6 : 1}
              placeholder={mode === "signup" ? "Create a password (min 6 characters)" : "Enter your password"}
            />
          </label>

          {error && <div className="form-error" role="alert">{error}</div>}

          <button className="button button-primary button-wide" disabled={busy}>
            {busy
              ? mode === "signin" ? "Signing in…" : "Creating account…"
              : mode === "signin" ? "Sign in" : "Sign up & Enter workspace"}
            <ArrowUpRight size={16} />
          </button>

          <div className="auth-switch">
            {mode === "signin" ? (
              <span>
                Don't have an account?{" "}
                <button type="button" onClick={() => { setMode("signup"); setError(""); }}>
                  Sign up
                </button>
              </span>
            ) : (
              <span>
                Already have an account?{" "}
                <button type="button" onClick={() => { setMode("signin"); setError(""); }}>
                  Sign in
                </button>
              </span>
            )}
          </div>

          <p className="login-note">
            <ShieldCheck size={14} />
            {mode === "signin"
              ? "Authorized staff only. Demo accounts are configured by your administrator."
              : "New accounts get immediate receptionist access. Administrators are assigned separately."}
          </p>
        </form>
      </section>
    </div>
  );
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  useEffect(() => {
    let current = true;
    setBusy(true);
    load().then((result) => { if (current) { setValue(result); setError(""); } })
      .catch((err: unknown) => { if (current) setError(message(err)); })
      .finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
    // The passed-in API loaders are stable, while refresh and caller dependencies trigger reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);
  return { value, error, busy, reload };
}

function StatePanel({ busy, error, empty, onRetry }: { busy: boolean; error?: string; empty?: boolean; onRetry?: () => void }) {
  if (busy) return <div className="empty-state"><span className="loader" />Loading data…</div>;
  if (error) return <div className="empty-state error-state"><AlertTriangle size={20} /><span>{error}</span>{onRetry && <button className="button button-secondary" onClick={onRetry}>Retry</button>}</div>;
  if (empty) return <div className="empty-state"><Search size={21} /><span>No records yet. Register a patient to start collecting live data.</span></div>;
  return null;
}

function MetricCard({ label, value, unit, note, icon: Icon, tone = "" }: { label: string; value: string | number; unit?: string; note: string; icon: typeof Users; tone?: string }) {
  return <article className="metric-card"><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={17} /></span></div><div className="metric-value">{value}<small>{unit}</small></div><div className="metric-note"><span className="neutral-note"><Activity size={13} /></span>{note}</div></article>;
}

function OverviewPage({ onNavigate, notify }: { onNavigate: (page: Page) => void; notify: (text: string) => void }) {
  const { value, error, busy, reload } = useLoad<Overview>(api.overview);
  const departments = value?.departments ?? [];
  const maxWait = Math.max(1, ...departments.map((item) => item.waiting));
  return <>
    <PageHeading eyebrow={new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }).toUpperCase()} title="Operations overview" description="A real-time snapshot of today's outpatient activity."
      action={<button className="button button-primary" onClick={() => onNavigate("registration")}><Plus size={16} /> Register patient</button>} />
    <div className="notice-banner"><span className="notice-icon"><ShieldCheck size={18} /></span><div><strong>Demo workspace</strong><span>Synthetic patient data only. Predictions are estimates; no clinical or operational impact is implied.</span></div><button onClick={() => notify("All dashboard metrics are sourced from the live service database.")} className="banner-action">About this data <ArrowUpRight size={14} /></button></div>
    <StatePanel busy={busy} error={error} onRetry={reload} />
    {!busy && !error && value && <>
      <div className="metrics-grid">
        <MetricCard label="Patients registered" value={value.total_registered} note="All records in this workspace" icon={Users} />
        <MetricCard label="Currently waiting" value={value.waiting} note="Live active queue" icon={Clock3} tone="tone-orange" />
        <MetricCard label="In consultation" value={value.in_service} note="Active service sessions" icon={Stethoscope} tone="tone-blue" />
        <MetricCard label="Completed" value={value.completed} note="Recorded completed tickets" icon={Check} tone="tone-green" />
      </div>
      <div className="dashboard-grid">
        <section className="panel dept-panel"><div className="panel-heading"><div><h2>Department pulse</h2><p>Current queue volume by department</p></div><button className="text-button" onClick={() => onNavigate("queue")}>Open live queue <ArrowUpRight size={14} /></button></div>
          {departments.length === 0 ? <div className="empty-state">No departments are configured.</div> : departments.map((dept) => <div className="dept-row" key={dept.department_id}><div className="dept-heading"><span className="dept-avatar">{dept.department.slice(0, 2).toUpperCase()}</span><div><strong>{dept.department}</strong><small>{dept.available_staff} staff available · {dept.in_service} in service</small></div><span className="dept-count">{dept.waiting}<small>waiting</small></span></div><div className="progress-track"><span style={{ width: `${Math.max(3, (dept.waiting / maxWait) * 100)}%` }} /></div></div>)}
        </section>
        <section className="panel insight-panel"><div className="panel-heading"><div><h2>Waiting time</h2><p>Measured from completed service sessions</p></div><span className="mini-chart-icon"><Activity size={16} /></span></div>
          <div className="wait-number">{value.actual_average_wait_minutes == null ? "—" : value.actual_average_wait_minutes}<small>{value.actual_average_wait_minutes == null ? "" : "min"}</small></div>
          <p className="muted small">Actual average wait; shown only when completed service records exist.</p>
          <div className="insight-divider" /><p className="insight-label">DATA STATUS</p><p className="insight-copy">{value.data_label}</p>
          <button className="button button-secondary button-wide" onClick={() => onNavigate("analytics")}>Explore analytics <ArrowUpRight size={15} /></button>
        </section>
      </div>
      <div className="section-title"><div><h2>Quick actions</h2><p>Common tasks for your operations team</p></div></div>
      <div className="quick-grid">
        <button className="quick-card" onClick={() => onNavigate("registration")}><span className="quick-icon quick-teal"><Plus size={18} /></span><strong>Register a patient</strong><small>Issue a department queue token</small><ArrowUpRight size={15} /></button>
        <button className="quick-card" onClick={() => onNavigate("simulation")}><span className="quick-icon quick-violet"><BarChart3 size={18} /></span><strong>Run a scenario</strong><small>Compare staffing assumptions</small><ArrowUpRight size={15} /></button>
        <button className="quick-card" onClick={() => onNavigate("alerts")}><span className="quick-icon quick-orange"><AlertTriangle size={18} /></span><strong>Review bottlenecks</strong><small>See queue-length signals</small><ArrowUpRight size={15} /></button>
      </div>
    </>}
  </>;
}

function QueuePage({ notify }: { notify: (text: string) => void }) {
  const [department, setDepartment] = useState("");
  const departments = useLoad<Department[]>(api.departments);
  const queue = useLoad<Ticket[]>(() => api.queue(department || undefined), [department]);
  const [search, setSearch] = useState("");
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [busyId, setBusyId] = useState("");
  const filtered = useMemo(() => (queue.value ?? []).filter((ticket) =>
    `${ticket.token} ${ticket.patient_reference} ${ticket.display_name ?? ""} ${ticket.department}`.toLowerCase().includes(search.toLowerCase())
  ), [queue.value, search]);
  async function transition(ticket: Ticket, next: string) {
    setBusyId(ticket.id);
    try { await api.updateStatus(ticket.id, next); queue.reload(); notify(`Ticket ${ticket.token} moved to ${next.replace("_", " ")}.`); }
    catch (error) { notify(message(error)); }
    finally { setBusyId(""); }
  }
  async function predict(ticket: Ticket) {
    try { setPrediction(await api.predict(ticket.id)); }
    catch (error) { notify(message(error)); }
  }
  return <>
    <PageHeading eyebrow="PATIENT FLOW" title="Live queue" description="Track arrivals through the outpatient service queue. Updates are saved to the database." action={<button className="button button-secondary" onClick={queue.reload}><RefreshCw size={15} /> Refresh</button>} />
    <section className="panel table-panel"><div className="table-toolbar"><label className="search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search token or reference" /></label>
      <select aria-label="Filter department" value={department} onChange={(event) => setDepartment(event.target.value)}><option value="">All departments</option>{(departments.value ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
      <StatePanel busy={queue.busy || departments.busy} error={queue.error || departments.error} empty={!queue.busy && filtered.length === 0} onRetry={queue.reload} />
      {!queue.busy && !queue.error && filtered.length > 0 && <div className="table-wrap"><table><thead><tr><th>QUEUE TOKEN</th><th>PATIENT REF</th><th>DEPARTMENT</th><th>ARRIVAL</th><th>QUEUE STATUS</th><th>POSITION</th><th>ACTIONS</th></tr></thead>
        <tbody>{filtered.map((ticket) => <tr key={ticket.id}><td><strong className="token-cell">{ticket.token}</strong><small>{ticket.appointment_type}</small></td><td>{ticket.patient_reference}<small>{ticket.display_name || "Demo patient"}</small></td><td>{ticket.department}</td><td>{new Date(ticket.arrival_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td><td><StatusPill status={ticket.status} /></td><td>{ticket.patients_ahead + (ticket.status === "waiting" ? 1 : 0)}</td><td className="action-cell">
          {ticket.status === "waiting" && <button className="table-action" disabled={busyId === ticket.id} onClick={() => transition(ticket, "in_service")}>Start</button>}
          {ticket.status === "in_service" && <button className="table-action" disabled={busyId === ticket.id} onClick={() => transition(ticket, "completed")}>Complete</button>}
          {ticket.status === "waiting" && <button className="table-action subtle-action" onClick={() => predict(ticket)}>Predict</button>}
          {ticket.status === "waiting" && <button className="table-action subtle-action" disabled={busyId === ticket.id} onClick={() => transition(ticket, "no_show")}>No-show</button>}
        </td></tr>)}</tbody></table></div>}
    </section>
    {prediction && <div className="modal-backdrop" role="presentation" onClick={() => setPrediction(null)}><section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="prediction-title" onClick={(event) => event.stopPropagation()}>
    <button className="modal-close" aria-label="Close" onClick={() => setPrediction(null)}><X size={18} /></button><span className="eyebrow">WAIT-TIME ESTIMATE</span><h2 id="prediction-title">{prediction.predicted_minutes == null ? "Unavailable" : `${prediction.predicted_minutes} min`}</h2><p className="muted">{prediction.lower_minutes == null || prediction.upper_minutes == null ? prediction.model : `Planning range ${prediction.lower_minutes}–${prediction.upper_minutes} min · ${prediction.model}`}</p><p className="callout">{prediction.uncertainty_note}</p><ul>{prediction.factors.map((factor) => <li key={factor}>{factor}</li>)}</ul><button className="button button-primary" onClick={() => setPrediction(null)}>Done</button>
    </section></div>}
  </>;
}

function StatusPill({ status }: { status: string }) {
  const label = status.replace("_", " ");
  return <span className={`status-pill status-${status}`}><i />{label}</span>;
}

function RegistrationPage({ notify }: { notify: (text: string) => void }) {
  const { value: departments, error, busy, reload } = useLoad<Department[]>(api.departments);
  const [department, setDepartment] = useState("");
  const [type, setType] = useState("walk-in");
  const [priority, setPriority] = useState("routine");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<Ticket | null>(null);
  const options = departments ?? [];
  useEffect(() => { if (!department && options.length) setDepartment(options[0].id); }, [department, options]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!department) { notify("Choose a department first."); return; }
    setSaving(true);
    try {
      setCreated(await api.register({
        department_id: department, appointment_type: type, priority,
        ...(name.trim() ? { display_name: name.trim() } : {}),
      }));
      notify("Patient registered and queue token created.");
      setName("");
    } catch (err) { notify(message(err)); }
    finally { setSaving(false); }
  }
  return <>
    <PageHeading eyebrow="FRONT DESK" title="Patient registration" description="Create a synthetic patient reference and issue a department-specific queue token." />
    <div className="form-layout"><form className="panel registration-form" onSubmit={submit}>
      <div className="form-section-title"><span className="step-number">01</span><div><h2>Visit details</h2><p>Only minimal operational details are needed.</p></div></div>
      {error && <StatePanel busy={busy} error={error} onRetry={reload} />}
      <label>Department<select required value={department} disabled={busy || !options.length} onChange={(event) => setDepartment(event.target.value)}><option value="">Select department</option>{options.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.available_staff} staff</option>)}</select></label>
      <label>Display name <span className="optional">(optional; demo only)</span><input maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Demo patient 01" /></label>
      <div className="form-row"><label>Visit type<select value={type} onChange={(event) => setType(event.target.value)}><option value="walk-in">Walk-in</option><option value="appointment">Appointment</option></select></label>
        <label>Queue category<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="routine">Routine</option><option value="priority">Staff-designated priority</option></select><small>Clinical triage remains a professional decision.</small></label></div>
      <div className="form-foot"><span><ShieldCheck size={15} /> No medical or contact data collected</span><button className="button button-primary" disabled={saving || busy}>{saving ? "Creating token…" : "Create queue token"}<ArrowUpRight size={15} /></button></div>
    </form>
      <aside className="registration-aside"><div className="aside-illustration"><div className="circle circle-one" /><div className="circle circle-two" /><div className="queue-ticket"><span>QUEUE TOKEN</span><strong>{created?.token ?? "—"}</strong><small>OUTPATIENT · TODAY</small></div><div className="float-check"><Check size={18} /></div></div>
        <div className="aside-copy"><span className="eyebrow">WHAT HAPPENS NEXT</span><h3>One token, a clearer queue.</h3><p>Each ticket gets a private patient reference. Share it with the visitor so they can check their own queue status without seeing other patients' details.</p></div>
        {created && <div className="created-card"><span className="status-pill status-waiting"><i />WAITING</span><strong>{created.patient_reference}</strong><small>{created.department} · {created.patients_ahead + 1} in queue</small><button className="text-button" onClick={() => { navigator.clipboard?.writeText(created.patient_reference).then(() => notify("Patient reference copied.")); }}>Copy patient reference <Command size={13} /></button></div>}
      </aside>
    </div>
  </>;
}

function SimulationPage({ user, notify }: { user: User; notify: (text: string) => void }) {
  const [patients, setPatients] = useState(120);
  const [rate, setRate] = useState(12);
  const [duration, setDuration] = useState(15);
  const [doctors, setDoctors] = useState(2);
  const [extra, setExtra] = useState(1);
  const [seed, setSeed] = useState(42);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    try { setResult(await api.simulate({ patients, arrival_rate_per_hour: rate, service_mean_minutes: duration, baseline_doctors: doctors, alternative_doctors: doctors + extra, seed })); }
    catch (error) { notify(message(error)); }
    finally { setBusy(false); }
  }
  if (user.role !== "admin") {
    return <PageHeading eyebrow="WHAT-IF ANALYSIS" title="Administrator access required" description="Only administrators can run and store staffing simulations." />;
  }
  return <>
    <PageHeading eyebrow="WHAT-IF ANALYSIS" title="Scenario lab" description="Compare staffing scenarios on the same synthetic arrival pattern." />
    <div className="sim-layout"><form className="panel sim-controls" onSubmit={run}><div className="panel-heading"><div><h2>Simulation inputs</h2><p>Set assumptions for one operating day</p></div><span className="sim-chip">SIMULATED</span></div>
      <label>Patients arriving <input type="number" min={1} max={5000} value={patients} onChange={(event) => setPatients(Number(event.target.value))} /></label>
      <label>Arrival rate <span className="input-unit"><input type="number" min={0.1} max={300} step={0.5} value={rate} onChange={(event) => setRate(Number(event.target.value))} /><small>patients / hour</small></span></label>
      <label>Average service duration <span className="input-unit"><input type="number" min={1} max={240} value={duration} onChange={(event) => setDuration(Number(event.target.value))} /><small>minutes</small></span></label>
      <div className="form-row"><label>Current doctors<input type="number" min={0} max={100} value={doctors} onChange={(event) => setDoctors(Number(event.target.value))} /></label><label>Extra doctors<input type="number" min={0} max={100} value={extra} onChange={(event) => setExtra(Number(event.target.value))} /></label></div>
      <label>Random seed <input type="number" min={0} value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      <button className="button button-primary button-wide" disabled={busy}>{busy ? "Running simulation…" : "Run comparison"}<ArrowUpRight size={15} /></button>
      <p className="form-footnote"><ShieldCheck size={14} /> Same arrival times and service random seed in each scenario.</p>
    </form>
    <section className="sim-results"><div className="sim-explainer"><span className="notice-icon"><Activity size={18} /></span><div><strong>Simulation, not a forecast</strong><p>Event-based queue outcomes use generated arrivals and service durations. They are not observed hospital results.</p></div></div>
      {!result && <div className="panel empty-sim"><BarChart3 size={27} /><h3>Your comparison will appear here</h3><p>Adjust the inputs and run a scenario to explore staffing trade-offs.</p></div>}
      {result && <><div className="sim-result-heading"><div><span className="eyebrow">REPEATABLE RUN · SEED {result.seed}</span><h2>Staffing scenario comparison</h2></div><span className="sim-chip">SIMULATED</span></div>
        <div className="scenario-cards">{[[`Current · ${doctors} doctors`, result.baseline], [`Alternative · ${doctors + extra} doctors`, result.alternative]].map(([label, data], index) => {
          const scenario = data as SimulationResult["baseline"];
          return <article className={`panel scenario-card ${index ? "scenario-alt" : ""}`} key={label as string}><span className="scenario-label">{label as string}</span><div className="scenario-main">{scenario.average_wait_minutes ?? "—"}<small>{scenario.average_wait_minutes == null ? "" : "min avg wait"}</small></div><div className="scenario-stat"><span>90th percentile</span><strong>{scenario.p90_wait_minutes ?? "—"} min</strong></div><div className="scenario-stat"><span>Maximum queue</span><strong>{scenario.maximum_queue}</strong></div><div className="scenario-stat"><span>Staff utilization</span><strong>{scenario.staff_utilization_percent}%</strong></div><div className="scenario-stat"><span>Throughput</span><strong>{scenario.throughput_per_hour}/hr</strong></div></article>;
        })}</div>
        <div className="panel tradeoff-panel"><div><span className="eyebrow">ALTERNATIVE VS CURRENT</span><h3>Average waiting-time difference</h3></div><strong className={(result.difference.average_wait_minutes ?? 0) <= 0 ? "positive-delta" : "negative-delta"}>{result.difference.average_wait_minutes == null ? "Not measurable" : `${result.difference.average_wait_minutes > 0 ? "+" : ""}${result.difference.average_wait_minutes} min`}</strong></div>
      </>}
    </section></div>
  </>;
}

function AnalyticsPage({ notify }: { notify: (text: string) => void }) {
  const overview = useLoad<Overview>(api.overview);
  const trends = useLoad<Array<{ hour: string; registered: number }>>(api.trends);
  const evaluation = useLoad<{ evaluated_predictions: number; mae_minutes: number | null; note?: string }>(
    () => fetch(`${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "")}/api/predictions/evaluation`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("flowcare-token") ?? ""}` },
    }).then(async (response) => { if (!response.ok) throw new Error("Evaluation could not be loaded."); return response.json(); }),
  );
  return <>
    <PageHeading eyebrow="OPERATIONAL PERFORMANCE" title="Analytics" description="Explore recorded queue activity and prediction evaluation from this database." action={<button className="button button-secondary" onClick={() => { overview.reload(); trends.reload(); evaluation.reload(); notify("Refreshing analytics."); }}><RefreshCw size={15} /> Refresh</button>} />
    <div className="analytics-metrics"><article className="panel analytics-stat"><span>ACTUAL AVERAGE WAIT</span><strong>{overview.value?.actual_average_wait_minutes == null ? "—" : `${overview.value.actual_average_wait_minutes} min`}</strong><small>Measured for completed records</small></article><article className="panel analytics-stat"><span>PREDICTION MAE</span><strong>{evaluation.value?.mae_minutes == null ? "—" : `${evaluation.value.mae_minutes} min`}</strong><small>{evaluation.value?.evaluated_predictions ?? 0} evaluated prediction(s)</small></article><article className="panel analytics-stat"><span>REGISTERED RECORDS</span><strong>{overview.value?.total_registered ?? "—"}</strong><small>Across all configured departments</small></article></div>
    <section className="panel chart-panel"><div className="panel-heading"><div><h2>Arrivals over time</h2><p>Actual registrations grouped by hour (local server time)</p></div><span className="chart-legend"><i /> Registered</span></div>
      <StatePanel busy={trends.busy || overview.busy || evaluation.busy} error={trends.error || overview.error || evaluation.error} onRetry={trends.reload} empty={!trends.busy && !(trends.value?.length)} />
      {!!trends.value?.length && <div className="chart-container"><ResponsiveContainer width="100%" height="100%"><AreaChart data={trends.value} margin={{ top: 8, right: 16, left: -14, bottom: 0 }}><defs><linearGradient id="arrivals" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#138a83" stopOpacity={0.22} /><stop offset="95%" stopColor="#138a83" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="#edf1f2" vertical={false} /><XAxis dataKey="hour" tickFormatter={(value: string) => value.slice(5, 16)} tick={{ fill: "#89989d", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fill: "#89989d", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip /><Area type="monotone" dataKey="registered" stroke="#138a83" strokeWidth={2.5} fill="url(#arrivals)" /></AreaChart></ResponsiveContainer></div>}
    </section>
    <div className="data-disclaimer"><ShieldCheck size={16} /><span>Historical charts show actual database registrations. No mock trend data is inserted when records are empty. Synthetic training metrics do not demonstrate real-world performance.</span></div>
  </>;
}

function AlertsPage({ notify }: { notify: (text: string) => void }) {
  const alerts = useLoad<Array<{ department: string; severity: string; waiting: number; message: string }>>(api.bottlenecks);
  return <>
    <PageHeading eyebrow="QUEUE MONITORING" title="Bottleneck signals" description="Queue-length indicators for review by hospital operations staff." action={<button className="button button-secondary" onClick={alerts.reload}><RefreshCw size={15} /> Refresh</button>} />
    <div className="notice-banner"><span className="notice-icon"><AlertTriangle size={18} /></span><div><strong>Signals need human interpretation</strong><span>Queue size can indicate congestion; it does not establish its cause or prescribe clinical action.</span></div></div>
    <StatePanel busy={alerts.busy} error={alerts.error} onRetry={alerts.reload} empty={!alerts.busy && !(alerts.value?.length)} />
    {!!alerts.value?.length && <div className="alerts-list">{alerts.value.map((alert) => <article className="panel alert-card" key={alert.department}><span className={`alert-severity severity-${alert.severity}`}><AlertTriangle size={17} /></span><div className="alert-body"><div><span className="eyebrow">{alert.severity} SIGNAL</span><h2>{alert.department}</h2></div><p>{alert.message}</p><small>{alert.waiting} currently waiting · review current staffing and arrival conditions</small></div><button className="button button-secondary" onClick={() => notify(`Review ${alert.department} queue, staff availability, and arrival conditions before deciding on an action.`)}>Review signal</button></article>)}</div>}
  </>;
}

function StaffPage({ user, notify }: { user: User; notify: (text: string) => void }) {
  const departments = useLoad<Department[]>(api.departments);
  const staff = useLoad<Awaited<ReturnType<typeof api.staff>>>(api.staff);
  const [creating, setCreating] = useState(false);
  const [addingDepartment, setAddingDepartment] = useState(false);
  const [staffDraft, setStaffDraft] = useState({ display_name: "", email: "", password: "", role: "receptionist" });
  const [departmentDraft, setDepartmentDraft] = useState({
    code: "",
    name: "",
    available_staff: 2,
    default_service_minutes: 15,
  });
  if (user.role !== "admin") return <PageHeading eyebrow="ADMINISTRATION" title="Access restricted" description="Only administrators can manage accounts and staff availability." />;
  async function submitStaff(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createStaff(staffDraft);
      setStaffDraft({ display_name: "", email: "", password: "", role: "receptionist" });
      setCreating(false); staff.reload(); notify("Staff account created.");
    } catch (error) { notify(message(error)); }
  }
  async function submitDepartment(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createDepartment(departmentDraft);
      setDepartmentDraft({ code: "", name: "", available_staff: 2, default_service_minutes: 15 });
      setAddingDepartment(false); departments.reload(); notify("Department created.");
    } catch (error) { notify(message(error)); }
  }
  async function changeAvailability(dept: Department, value: number) {
    try { await api.updateAvailability(dept.id, value); departments.reload(); notify(`${dept.name} availability updated.`); }
    catch (error) { notify(message(error)); }
  }
  return <>
    <PageHeading eyebrow="ADMINISTRATION" title="Staff & departments" description="Manage staff accounts and department availability." action={<div className="heading-actions"><button className="button button-secondary" onClick={() => setAddingDepartment(!addingDepartment)}><Plus size={16} /> Add department</button><button className="button button-primary" onClick={() => setCreating(!creating)}><Plus size={16} /> Add staff account</button></div>} />
    {addingDepartment && <form className="panel staff-create" onSubmit={submitDepartment}><h2>New department</h2><div className="form-row"><label>Department name<input required minLength={2} maxLength={120} value={departmentDraft.name} onChange={(e) => setDepartmentDraft({ ...departmentDraft, name: e.target.value })} /></label><label>Code<input required minLength={2} maxLength={10} pattern="[A-Z0-9]+" value={departmentDraft.code} onChange={(e) => setDepartmentDraft({ ...departmentDraft, code: e.target.value.toUpperCase() })} /></label></div><div className="form-row"><label>Available staff<input type="number" required min={0} max={100} value={departmentDraft.available_staff} onChange={(e) => setDepartmentDraft({ ...departmentDraft, available_staff: Number(e.target.value) })} /></label><label>Typical service minutes<input type="number" required min={1} max={240} value={departmentDraft.default_service_minutes} onChange={(e) => setDepartmentDraft({ ...departmentDraft, default_service_minutes: Number(e.target.value) })} /></label></div><button className="button button-primary">Create department</button></form>}
    {creating && <form className="panel staff-create" onSubmit={submitStaff}><h2>New staff account</h2><div className="form-row"><label>Name<input required maxLength={120} value={staffDraft.display_name} onChange={(e) => setStaffDraft({ ...staffDraft, display_name: e.target.value })} /></label><label>Email<input required type="email" value={staffDraft.email} onChange={(e) => setStaffDraft({ ...staffDraft, email: e.target.value })} /></label></div><div className="form-row"><label>Role<select value={staffDraft.role} onChange={(e) => setStaffDraft({ ...staffDraft, role: e.target.value })}><option value="receptionist">Receptionist</option><option value="staff">Department staff</option><option value="admin">Administrator</option></select></label><label>Temporary password<input required type="password" minLength={12} value={staffDraft.password} onChange={(e) => setStaffDraft({ ...staffDraft, password: e.target.value })} /><small>At least 12 characters; share securely outside this app.</small></label></div><button className="button button-primary">Create account</button></form>}
    <div className="management-grid"><section className="panel table-panel"><div className="panel-heading"><div><h2>Staff accounts</h2><p>Role-based access to FlowCare</p></div></div><StatePanel busy={staff.busy} error={staff.error} onRetry={staff.reload} empty={!staff.busy && !(staff.value?.length)} />{!!staff.value?.length && <div className="staff-list">{staff.value.map((item) => <div className="staff-row" key={item.id}><span className="avatar">{item.display_name[0]}</span><div><strong>{item.display_name}</strong><small>{item.email}</small></div><span className="role-tag">{item.role}</span></div>)}</div>}</section>
      <section className="panel department-manage"><div className="panel-heading"><div><h2>Department staffing</h2><p>Available staff for prediction inputs</p></div></div><StatePanel busy={departments.busy} error={departments.error} onRetry={departments.reload} empty={!departments.busy && !(departments.value?.length)} />{departments.value?.map((dept) => <div className="availability-row" key={dept.id}><div><strong>{dept.name}</strong><small>{dept.default_service_minutes} min typical service</small></div><label className="staff-count">{dept.available_staff}<small>available</small></label><button className="icon-button" aria-label={`Decrease ${dept.name} staffing`} disabled={dept.available_staff <= 0} onClick={() => changeAvailability(dept, dept.available_staff - 1)}>−</button><button className="icon-button" aria-label={`Increase ${dept.name} staffing`} onClick={() => changeAvailability(dept, dept.available_staff + 1)}>+</button></div>)}</section></div>
  </>;
}

function SettingsPage({ user, notify }: { user: User; notify: (text: string) => void }) {
  const logs = useLoad<Awaited<ReturnType<typeof api.auditLogs>>>(
    () => user.role === "admin" ? api.auditLogs() : Promise.resolve([]),
    [user.role],
  );
  return <>
    <PageHeading eyebrow="SYSTEM" title="Settings & audit" description="Review your access role and recent administrative activity." />
    <div className="settings-grid"><section className="panel setting-card"><span className="quick-icon quick-teal"><ShieldCheck size={19} /></span><h2>Signed-in account</h2><p>{user.display_name}</p><div className="setting-row"><span>Email</span><strong>{user.email}</strong></div><div className="setting-row"><span>Role</span><strong className="role-tag">{user.role}</strong></div><div className="setting-row"><span>Patient data mode</span><strong>Synthetic demo</strong></div><button className="button button-secondary button-wide" onClick={() => notify("Server configuration is managed through environment variables. See the project README.")}>Configuration guide <ArrowUpRight size={14} /></button></section>
      <section className="panel audit-card"><div className="panel-heading"><div><h2>Recent audit activity</h2><p>Administrative changes and queue transitions</p></div>{user.role === "admin" && <button className="icon-button" onClick={logs.reload} aria-label="Refresh audit log"><RefreshCw size={15} /></button>}</div>{user.role !== "admin" ? <div className="empty-state">Audit records are restricted to administrators.</div> : <><StatePanel busy={logs.busy} error={logs.error} onRetry={logs.reload} empty={!logs.busy && !(logs.value?.length)} />{logs.value?.map((item) => <div className="audit-row" key={item.id}><span className="audit-dot" /><div><strong>{item.action.replaceAll(".", " ")}</strong><small>{item.resource_type} · {item.resource_id?.slice(0, 8) ?? "system"}</small></div><time>{new Date(item.occurred_at).toLocaleString()}</time></div>)}</>}</section></div>
  </>;
}

export default App;
