"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Copy, KeyRound, Plus, RefreshCw, Search } from "lucide-react";
import { workspace } from "@/lib/ai-workspace";

type Credential = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  usage_count: number;
  created_at: string;
  secret?: string;
  notice?: string;
};

const endpoints = [
  { method: "GET", path: "/api/v1/dashboard", category: "Command", scope: "dashboard.read", description: "Tenant dashboard metrics and recent activity." },
  { method: "GET", path: "/api/v1/reports", category: "Reports", scope: "reports.read", description: "Search tenant report metadata." },
  { method: "GET", path: "/api/v1/reports/{id}", category: "Reports", scope: "reports.read", description: "Preview an authorized report snapshot." },
  { method: "GET", path: "/api/v1/commerce/transactions", category: "Commerce", scope: "commerce.read", description: "Paginated tenant payment and refund records." },
  { method: "GET", path: "/api/v1/incidents", category: "Security", scope: "incidents.read", description: "Tenant incident inventory." },
  { method: "GET", path: "/api/v1/assets", category: "Inventory", scope: "assets.read", description: "Tenant asset inventory." },
  { method: "GET", path: "/api/v1/forensic-cases", category: "Forensics", scope: "forensics.read", description: "Authorized forensic case inventory." },
];

export default function DeveloperPortal() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [selected, setSelected] = useState(endpoints[0]);
  const [dialog, setDialog] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["api.read"]);
  const [days, setDays] = useState("30");
  const [issued, setIssued] = useState<Credential | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setCredentials(await workspace<Credential[]>("developer/credentials"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "API credentials are unavailable.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const expires = new Date(Date.now() + Number(days) * 24 * 60 * 60 * 1000).toISOString();
      const result = await workspace<Credential>("developer/credentials", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, scopes, expires_at: expires }),
      });
      setIssued(result);
      setDialog(false);
      setName("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "API credential could not be created.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      await workspace<Credential>(`developer/credentials/${id}/revoke`, { method: "POST" });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "API credential could not be revoked.");
    } finally {
      setBusy(false);
    }
  };

  const visibleEndpoints = endpoints.filter((endpoint) =>
    (category === "All" || endpoint.category === category)
    && `${endpoint.method} ${endpoint.path} ${endpoint.description}`.toLowerCase().includes(query.toLowerCase()));
  const categories = ["All", ...Array.from(new Set(endpoints.map((endpoint) => endpoint.category)))];

  return <main className="module-page developer-page">
    <header className="module-heading"><div><div className="eyebrow">DEVELOPER PLATFORM</div><h1>API portal</h1><p>Scoped read credentials and actual tenant API documentation.</p></div><div className="module-actions"><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button><button className="primary-button" type="button" onClick={() => setDialog(true)}><Plus size={15}/>Create credential</button></div></header>
    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Developer portal request failed</strong><span>{error}</span></div></div>}
    {issued && <div className="notice success-notice" role="status"><KeyRound size={16}/><div><strong>Credential issued once</strong><span>{issued.notice}</span></div><code>{issued.secret}</code><button type="button" className="icon-button" aria-label="Copy secret" onClick={() => void navigator.clipboard?.writeText(issued.secret || "")}><Copy size={14}/></button></div>}
    <section className="developer-layout">
      <aside className="panel developer-nav"><div className="table-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search endpoints"/></div><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select></label><div className="developer-endpoints">{visibleEndpoints.map((endpoint) => <button type="button" key={endpoint.path} className={selected.path === endpoint.path ? "selected" : ""} onClick={() => setSelected(endpoint)}><b>{endpoint.method}</b><span>{endpoint.path}</span></button>)}</div></aside>
      <section className="panel developer-details"><div className="panel-kicker">{selected.category} / AUTHORIZED READ</div><h2>{selected.method} {selected.path}</h2><p>{selected.description}</p><h3>Required scope</h3><code>{selected.scope}</code><h3>Authentication</h3><pre>{`Authorization: Bearer <YOUR_API_CREDENTIAL>`}</pre><h3>Example request</h3><pre>{`curl.exe -H "Authorization: Bearer <YOUR_API_CREDENTIAL>" http://127.0.0.1:8002${selected.path.replace("{id}", "<REPORT_ID>")}`}</pre><h3>Response</h3><pre>{"{\n  \"tenant_scoped\": true,\n  \"data\": \"Authorized response fields\"\n}"}</pre></section>
      <aside className="panel developer-credentials"><div className="panel-heading"><div><div className="panel-kicker">CREDENTIALS</div><h2>Organization keys</h2></div></div>{credentials.length === 0 ? <div className="module-empty"><KeyRound size={20}/><strong>No credentials</strong></div> : <div className="credential-list">{credentials.map((credential) => <article key={credential.id}><strong>{credential.name}</strong><code>{credential.prefix}…</code><span>{credential.scopes.join(", ")}</span><span>Expires {new Date(credential.expires_at).toLocaleString()}</span><span>{credential.revoked_at ? "Revoked" : `${credential.usage_count} uses`}</span><button type="button" className="outline-button" disabled={!!credential.revoked_at} onClick={() => void revoke(credential.id)}>{credential.revoked_at ? "Revoked" : "Revoke"}</button></article>)}</div>}</aside>
    </section>
    {dialog && <div className="module-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(false); }}><form className="module-dialog" onSubmit={create}><div className="panel-heading"><div><div className="panel-kicker">NEW API CREDENTIAL</div><h2>Create scoped key</h2></div><button type="button" className="icon-button" onClick={() => setDialog(false)}>×</button></div><label>Name<input required minLength={2} maxLength={120} value={name} onChange={(event) => setName(event.target.value)}/></label><label>Expiration<select value={days} onChange={(event) => setDays(event.target.value)}><option value="30">30 days</option><option value="90">90 days</option><option value="365">365 days</option></select></label><fieldset className="developer-scopes"><legend>Read scopes</legend>{["api.read","dashboard.read","reports.read","commerce.read","incidents.read","assets.read","forensics.read","health.read"].map((scope) => <label key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={(event) => setScopes((current) => event.target.checked ? [...current, scope] : current.filter((item) => item !== scope))}/><span>{scope}</span></label>)}</fieldset><button className="primary-button" type="submit" disabled={busy || scopes.length === 0}>Create credential</button></form></div>}
  </main>;
}
