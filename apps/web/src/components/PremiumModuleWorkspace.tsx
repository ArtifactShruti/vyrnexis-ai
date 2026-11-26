"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Boxes, RefreshCw, Search, ShieldCheck, UserPlus, Users } from "lucide-react";

type Props = { module: string; title: string; description: string };

function displayValue(value: unknown) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function PremiumModuleWorkspace({ module, title, description }: Props) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const endpoints: Record<string, string> = {
        threats: "/api/workspace/admin/threat-intelligence",
        integrations: "/api/workspace/admin/integrations",
        notifications: "/api/workspace/admin/notifications",
        users: "/api/workspace/admin/users",
        audit: "/api/workspace/admin/audit",
        roles: "/api/workspace/admin/role-matrix",
        "super-admin": "/api/workspace/admin/platform",
        billing: "/api/workspace/ai/settings",
      };
      const response = await fetch(endpoints[module], { cache: "no-store" });
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Live records are unavailable.");
      if (module === "threats") {
        setRows([
          ...((body.entities || []) as Record<string, unknown>[]),
          ...((body.alerts || []) as Record<string, unknown>[]).map((item) => ({ ...item, name: item.rule, type: "alert" })),
        ]);
        setPayload(body);
      } else if (module === "roles") {
        setPayload(body);
        setRows((body.roles || []) as Record<string, unknown>[]);
      } else if (module === "billing") {
        setPayload(body);
        setRows([]);
      } else if (module === "super-admin") {
        setPayload(body);
        setRows([]);
      } else {
        setPayload(null);
        setRows(Array.isArray(body) ? body : []);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Live records are unavailable.");
    } finally {
      setBusy(false);
    }
  }, [module]);

  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => rows.filter((row) => JSON.stringify(row).toLowerCase().includes(query.toLowerCase())),
    [rows, query]);

  const createUser = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/workspace/admin/users", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ full_name: name, email, password, role }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "User creation failed.");
      setCreateOpen(false);
      setName("");
      setEmail("");
      setPassword("");
      setRole("viewer");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "User creation failed.");
    } finally {
      setBusy(false);
    }
  };

  return <main className="module-page">
    <header className="module-heading">
      <div>
        <div className="eyebrow">ENTERPRISE WORKSPACE</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="module-actions">
        <button className="outline-button" type="button" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={14} className={busy ? "spin" : ""} /> Refresh
        </button>
        {module === "users" && <button className="primary-button" type="button" onClick={() => setCreateOpen(true)}><UserPlus size={15}/> Add user</button>}
      </div>
    </header>

    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Request could not be completed</strong><span>{error}</span></div></div>}

    {module === "billing" && <section className="panel module-summary"><div className="module-summary-icon"><Boxes size={18}/></div><div><h2>Subscription management unavailable</h2><p>No subscription or billing provider is configured. This workspace shows only real AI usage policy and account data; no plan or charge status is inferred.</p></div></section>}

    {module === "super-admin" && payload && <section className="module-stat-grid">
      {[
        ["Organization", String(payload.organization && typeof payload.organization === "object" ? (payload.organization as {name:string}).name : "")],
        ["Users", String(payload.users)],
        ["Active users", String(payload.active_users)],
        ["Audit records", String(payload.audit_records)],
        ["Data sources", String(payload.data_sources)],
        ["Cross-tenant access", "Not available"],
      ].map(([label, value]) => <article className="metric-card" key={label}><div className="metric-top"><span>{label}</span><ShieldCheck size={15}/></div><div className="metric-number">{value}</div></article>)}
    </section>}

    {module === "billing" && payload && <section className="panel"><div className="panel-heading"><div><div className="panel-kicker">AUTHORIZED AI POLICY</div><h2>Usage and provider status</h2></div></div>
      <pre className="module-json">{JSON.stringify(payload, null, 2)}</pre>
    </section>}

    {module !== "billing" && module !== "super-admin" && <section className="panel module-table-panel">
      <div className="table-toolbar">
        <div className="table-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${title.toLowerCase()}`} aria-label={`Search ${title}`}/></div>
        <span className="table-count">{visible.length} records</span>
      </div>
      {visible.length === 0 ? <div className="module-empty"><Boxes size={21}/><strong>No records available</strong><span>Persisted tenant records will appear here when present.</span></div> :
        <div className="table-wrap"><table className="module-table"><thead><tr>{Object.keys(visible[0]).slice(0, 7).map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>
          {visible.map((row, index) => (
            <tr key={String(row.id || index)}>
              {Object.keys(row).slice(0, 7).map((key) => (
                <td key={key}>{displayValue(row[key])}</td>
              ))}
            </tr>
          ))}
        </tbody></table></div>}
    </section>}

    {createOpen && <div className="module-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCreateOpen(false); }}>
      <form className="module-dialog" onSubmit={createUser}>
        <div className="panel-heading"><div><div className="panel-kicker">ORGANIZATION ADMINISTRATION</div><h2>Add tenant user</h2></div><button type="button" className="icon-button" onClick={() => setCreateOpen(false)} aria-label="Close">×</button></div>
        <label>Full name<input required value={name} onChange={(event) => setName(event.target.value)}/></label>
        <label>Email<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)}/></label>
        <label>Password<input required type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)}/></label>
        <label>Role<select value={role} onChange={(event) => setRole(event.target.value)}><option value="viewer">Viewer</option><option value="member">Member</option><option value="security_analyst">Security analyst</option><option value="forensic_investigator">Forensic investigator</option><option value="business_analyst">Business analyst</option><option value="automation_engineer">Automation engineer</option><option value="organization_admin">Organization administrator</option></select></label>
        <button className="primary-button" type="submit" disabled={busy}><Users size={15}/> Create user</button>
      </form>
    </div>}
  </main>;
}
