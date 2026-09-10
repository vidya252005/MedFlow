import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api,
  type AlertRow,
  type AuditRow,
  type DlqRow,
  type EventRow,
  type Insights,
  type ModelsResponse,
  type Overview,
  type Patient,
  type Scenario,
  clearToken,
  getToken,
  setToken,
} from "./api";

type Tab = "overview" | "alerts" | "patients" | "models" | "dlq" | "audit";

export default function App() {
  const [token, setTok] = useState(getToken());
  if (!token) return <Login onLogin={(t) => setTok(t)} />;
  return (
    <Shell
      onLogout={() => {
        clearToken();
        setTok(null);
      }}
    />
  );
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("medflow");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(username, password);
      setToken(res.access_token);
      onLogin(res.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <p className="eyebrow">MedFlow</p>
        <h1>Synthetic healthcare event intelligence</h1>
        <p className="muted">
          Engineering prototype only. All patients, devices, and vitals are synthetic. Not a clinical system.
        </p>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Enter operations view"}
        </button>
        <p className="hint">admin / analyst / viewer · password `medflow`</p>
      </form>
    </div>
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [live, setLive] = useState<string[]>([]);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [dlq, setDlq] = useState<DlqRow[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [ov, ev, al, md, dq, au, pts, sc] = await Promise.all([
      api.overview(),
      api.events(),
      api.alerts(),
      api.models(),
      api.dlq().catch(() => ({ items: [] as DlqRow[] })),
      api.audit().catch(() => ({ items: [] as AuditRow[] })),
      api.patients(),
      api.scenarios().catch(() => ({ items: [] as Scenario[] })),
    ]);
    setOverview(ov);
    setEvents(ev.items);
    setAlerts(al.items);
    setModels(md);
    setDlq(dq.items);
    setAudit(au.items);
    setPatients(pts.items);
    setScenarios(sc.items);
  }, []);

  useEffect(() => {
    refresh().catch(() => undefined);
    const id = setInterval(() => refresh().catch(() => undefined), 4000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/stream?token=${token}`);
    ws.onmessage = (msg) => {
      setLive((prev) => [msg.data, ...prev].slice(0, 40));
      refresh().catch(() => undefined);
    };
    return () => ws.close();
  }, [refresh]);

  const openAlerts = useMemo(() => alerts.filter((a) => a.status === "OPEN" || a.status === "CREATED"), [alerts]);

  async function run(name: string) {
    const res = await api.runScenario(name, name === "duplicate_storm" ? 100 : 40, "pat_10092");
    setNotice(`Accepted ${res.accepted} events for ${name}`);
    await refresh();
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">MedFlow operations</p>
          <h1>Real-time synthetic event pipeline</h1>
        </div>
        <button className="ghost" onClick={onLogout}>
          Sign out
        </button>
      </header>
      <div className="banner">
        Synthetic healthcare data only. Outputs are engineering signals (anomaly, congestion, data quality) — never
        diagnoses or treatment.
      </div>
      <nav>
        {(
          [
            ["overview", "Overview"],
            ["alerts", "Alerts"],
            ["patients", "Patients"],
            ["models", "Models"],
            ["dlq", "Dead letters"],
            ["audit", "Audit"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <>
          <section className="kpis">
            <Kpi label="Events / min" value={overview?.events_per_min ?? "—"} />
            <Kpi label="Active patients" value={overview?.active_patients ?? "—"} />
            <Kpi label="Open alerts" value={overview?.open_alerts ?? "—"} accent={openAlerts.length > 0} />
            <Kpi
              label="p95 processing"
              value={overview?.p95_processing_latency_ms != null ? `${overview.p95_processing_latency_ms.toFixed(0)} ms` : "—"}
            />
            <Kpi
              label="Model success"
              value={overview ? `${(overview.model_success_rate * 100).toFixed(1)}%` : "—"}
            />
            <Kpi label="Consumer lag" value={overview?.consumer_lag ?? "—"} />
          </section>
          <div className="grid">
            <section className="panel">
              <h2>Scenario simulator</h2>
              <p className="muted">Drive the pipeline with named synthetic bursts. Idempotency is exercised by duplicate_storm.</p>
              <div className="scenario-grid">
                {scenarios.map((s) => (
                  <button key={s.name} className="scenario" onClick={() => run(s.name)}>
                    <strong>{s.name}</strong>
                    <span>{s.description}</span>
                  </button>
                ))}
              </div>
              {notice && <p className="notice">{notice}</p>}
            </section>
            <section className="panel">
              <h2>Live stream</h2>
              <div className="stream">
                {live.length === 0 && <p className="muted">Waiting for WebSocket alerts…</p>}
                {live.map((row, i) => (
                  <pre key={i}>{row}</pre>
                ))}
              </div>
            </section>
          </div>
          <section className="panel">
            <h2>Recent events</h2>
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Type</th>
                  <th>Patient</th>
                  <th>Status</th>
                  <th>Event</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.event_id}>
                    <td className="mono">{e.timestamp.replace("T", " ").slice(11, 19)}</td>
                    <td>{e.event_type}</td>
                    <td className="mono">{e.patient_id || "—"}</td>
                    <td>
                      <span className={`pill ${e.status.toLowerCase()}`}>{e.status}</span>
                    </td>
                    <td className="mono">{e.event_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {tab === "alerts" && (
        <section className="panel">
          <h2>Alert lifecycle</h2>
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Type</th>
                <th>Patient</th>
                <th>Status</th>
                <th>Message</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id}>
                  <td>
                    <span className={`sev ${a.severity}`}>{a.severity}</span>
                  </td>
                  <td>{a.alert_type}</td>
                  <td className="mono">{a.patient_id}</td>
                  <td>{a.status}</td>
                  <td>{a.message}</td>
                  <td className="actions">
                    {(a.status === "OPEN" || a.status === "CREATED") && (
                      <button onClick={() => api.ack(a.id).then(refresh)}>Ack</button>
                    )}
                    {a.status === "ACKNOWLEDGED" && (
                      <button onClick={() => api.resolve(a.id).then(refresh)}>Resolve</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "patients" && (
        <div className="grid">
          <section className="panel">
            <h2>Synthetic cohort</h2>
            <ul className="list">
              {patients.map((p) => (
                <li key={p.id}>
                  <button className="link" onClick={() => api.insights(p.id).then(setInsights)}>
                    {p.display_name}
                  </button>
                  <span className="muted">
                    {p.id} · {p.ward_id}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <h2>{insights?.patient.display_name || "Select a patient"}</h2>
            {insights && (
              <>
                <p className="muted">Timeline of events, decisions, and alerts. Feature windows use event time, not arrival time.</p>
                <h3>Decisions</h3>
                <ul className="list">
                  {insights.decisions.map((d) => (
                    <li key={d.id}>
                      <strong>
                        {d.severity} · {d.action}
                      </strong>
                      <span className="muted">score {d.decision_score} · {d.triggered_rules.join(", ") || "no rules"}</span>
                    </li>
                  ))}
                </ul>
                <h3>Alerts</h3>
                <ul className="list">
                  {insights.alerts.map((a) => (
                    <li key={a.id}>
                      {a.severity} {a.alert_type} · {a.status}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>
      )}

      {tab === "models" && (
        <section className="panel">
          <h2>Model registry & circuit breakers</h2>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Version</th>
                <th>p95</th>
                <th>Success</th>
                <th>Circuit</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {models &&
                Object.entries(models.registry).map(([name, meta]) => {
                  const stat = models.stats.find((s) => s.model_name === name);
                  const circuit = models.circuits[name]?.state || "CLOSED";
                  return (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="mono">{meta.version}</td>
                      <td>{stat ? `${stat.p95_ms} ms` : "—"}</td>
                      <td>{stat ? `${(stat.success_rate * 100).toFixed(1)}%` : "—"}</td>
                      <td>
                        <span className={`pill ${circuit.toLowerCase()}`}>{circuit}</span>
                      </td>
                      <td>{meta.shadow ? "shadow" : meta.fallback ? `fallback: ${meta.fallback}` : "primary"}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </section>
      )}

      {tab === "dlq" && (
        <section className="panel">
          <h2>Dead-letter queue</h2>
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Event</th>
                <th>Error</th>
                <th>Replayed</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {dlq.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.failure_code}</td>
                  <td className="mono">{row.event_id}</td>
                  <td>{row.error}</td>
                  <td>{row.replayed ? "yes" : "no"}</td>
                  <td>
                    {!row.replayed && <button onClick={() => api.replay(row.id).then(refresh)}>Replay</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "audit" && (
        <section className="panel">
          <h2>Audit log</h2>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.created_at.replace("T", " ").slice(0, 19)}</td>
                  <td>{row.actor}</td>
                  <td>{row.action}</td>
                  <td>{row.resource_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <article className={`kpi ${accent ? "accent" : ""}`}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}
