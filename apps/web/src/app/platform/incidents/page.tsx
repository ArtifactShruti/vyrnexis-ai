"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Plus, RefreshCw, Search, ShieldCheck, X } from "lucide-react";

type Incident = { id: string; title: string; severity: string; status: string; assignee_id?: string | null; assignee_name?: string | null; team?: string };
type Principal = { user: { role: string }; organization: { name: string } };
type SourceEvent = { id: string; title: string; source: string; source_reference: string; occurred_at: string };
type Member = { id: string; name: string; role: string; is_active: boolean };

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [level, setLevel] = useState("medium");
  const [description, setDescription] = useState("");
  const [inspectedId, setInspectedId] = useState("");
  const [sourceEvents, setSourceEvents] = useState<SourceEvent[] | null>(null);
  const [sourceError, setSourceError] = useState("");
  const [members, setMembers] = useState<Member[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      let response = await fetch("/api/incidents", { cache: "no-store" });
      if (response.status === 401) {
        const refreshed = await fetch("/api/auth/refresh", { method: "POST", cache: "no-store" });
        if (!refreshed.ok) {
          window.location.assign("/login");
          return;
        }
        response = await fetch("/api/incidents", { cache: "no-store" });
      }
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Incident records are unavailable.");
      setIncidents(body);
      const session = await fetch("/api/auth/session", { cache: "no-store" });
      if (session.ok) {
        const identity = await session.json();
        setPrincipal(identity);
        if (["owner", "organization_admin"].includes(identity.user.role)) {
          const memberResponse = await fetch("/api/workspace/admin/users", { cache: "no-store" });
          if (memberResponse.ok) setMembers((await memberResponse.json()).filter((member: Member) => member.is_active));
        }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Incident records are unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) { setSearch(id); setInspectedId(id); }
  }, []);
  useEffect(() => {
    if (!inspectedId || loading) return;
    const controller = new AbortController();
    fetch(`/api/detection/incidents/${encodeURIComponent(inspectedId)}/events`, {
      cache: "no-store", signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error("Linked events could not be loaded.");
      const records = await response.json();
      if (!controller.signal.aborted) setSourceEvents(records);
    }).catch(cause => { if (!controller.signal.aborted) setSourceError(cause.message); });
    return () => controller.abort();
  }, [inspectedId, loading]);

  function inspectIncident(id: string) {
    if (id === inspectedId) return;
    setSourceEvents(null);
    setSourceError("");
    setInspectedId(id);
  }

  const visible = useMemo(() => incidents.filter((incident) => {
    const matches = `${incident.title} ${incident.id} ${incident.status}`.toLowerCase().includes(search.toLowerCase());
    return matches && (severity === "all" || incident.severity.toLowerCase() === severity);
  }), [incidents, search, severity]);
  const canCreate = ["owner", "organization_admin", "security_analyst", "forensic_investigator"].includes(principal?.user.role || "");

  async function createIncident(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const response = await fetch("/api/incidents", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, severity: level, description }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Incident could not be created.");
      setIncidents((current) => [body, ...current]);
      setTitle("");
      setDescription("");
      setLevel("medium");
      setFormOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Incident could not be created.");
    } finally {
      setSaving(false);
    }
  }

  async function transitionIncident(incident: Incident, status: string) {
    setError("");
    try {
      const response = await fetch(`/api/incidents/${encodeURIComponent(incident.id)}/status`, {
        method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Incident status could not be updated.");
      setIncidents((current) => current.map((item) => item.id === body.id ? { ...item, status: body.status } : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Incident status could not be updated.");
      void load();
    }
  }

  async function assignIncident(incident: Incident, assigneeId: string) {
    setError("");
    try {
      const response = await fetch(`/api/incidents/${encodeURIComponent(incident.id)}/assignment`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ assignee_id: assigneeId || null, team: incident.team || "" }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Incident assignment could not be updated.");
      setIncidents((current) => current.map((item) => item.id === body.id ? body : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Incident assignment could not be updated.");
    }
  }

  return <main className="module-page">
    <header className="module-topbar"><Link href="/" className="module-back"><ArrowLeft size={15}/> Command center</Link><span className="module-org">{principal?.organization.name || "Organization workspace"}</span></header>
    <div className="module-content">
      <div className="module-heading"><div><div className="module-eyebrow">SECURITY OPERATIONS / CASE MANAGEMENT</div><h1>Incident manager</h1><p>Review and record organization incidents with role-checked access.</p></div><div className="module-actions"><button className="graph-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14}/> Refresh</button>{canCreate && <button className="module-primary" onClick={() => setFormOpen(true)}><Plus size={15}/> New incident</button>}</div></div>

      {error && <div className="module-alert" role="alert"><AlertTriangle size={16}/><span>{error}</span></div>}

      <section className="module-summary" aria-label="Incident summary"><div><span>IN VIEW</span><strong>{loading ? "..." : visible.length}</strong></div><div><span>OPEN</span><strong>{loading ? "..." : incidents.filter((incident) => incident.status !== "closed").length}</strong></div><div><span>CRITICAL / HIGH</span><strong>{loading ? "..." : incidents.filter((incident) => ["critical", "high"].includes(incident.severity.toLowerCase())).length}</strong></div><p><ShieldCheck size={15}/> Counts reflect persisted records in your organization.</p></section>

      <section className="module-panel">
        <div className="module-panel-heading"><div><h2>Incident queue</h2><span>{visible.length} matching records</span></div></div>
        <div className="module-toolbar">
          <label className="module-search"><Search size={14}/><input aria-label="Search incidents" placeholder="Search title, ID, or status" value={search} onChange={(event) => setSearch(event.target.value)}/></label>
          <label className="module-filter">Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
        </div>
        <div className="module-table-scroll">
          <table className="module-table">
            <thead><tr><th>INCIDENT</th><th>SEVERITY</th><th>STATUS</th><th>ASSIGNMENT</th><th>REFERENCE</th></tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={5} className="module-empty">Loading authorized incident records...</td></tr> : visible.map((incident) => (
                <tr key={incident.id}>
                  <td><div className="module-incident"><span><AlertTriangle size={15}/></span><div><strong>{incident.title}</strong><small>{incident.id}</small></div></div></td>
                  <td><span className={`module-severity ${incident.severity.toLowerCase()}`}>{incident.severity}</span></td>
                  <td>{canCreate ? <select className="module-status-select" aria-label={`Update ${incident.title} status`} value={incident.status} onChange={(event) => void transitionIncident(incident, event.target.value)}><option value={incident.status}>{incident.status}</option>{({open:["investigating","review","closed"],investigating:["review","contained","closed"],review:["investigating","closed"],contained:["investigating","closed"],closed:[]} as Record<string,string[]>)[incident.status].map((status) => <option key={status} value={status}>{status}</option>)}</select> : <span className="module-status">{incident.status}</span>}</td>
                  <td>{canCreate ? <select className="module-status-select" aria-label={`Assign ${incident.title}`} value={incident.assignee_id || ""} onChange={(event) => void assignIncident(incident, event.target.value)}><option value="">Unassigned</option>{members.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select> : <span className="module-status">{incident.assignee_name || "Unassigned"}</span>}</td>
                  <td><div className="incident-reference-actions"><Link className="module-reference" href="/platform/graph">Explore graph</Link><button type="button" className="graph-button" onClick={() => inspectIncident(incident.id)}>Source events</button></div></td>
                </tr>
              ))}
              {!loading && visible.length === 0 && <tr><td colSpan={5} className="module-empty">{incidents.length ? "No incidents match your filters." : "No incident records exist for this organization yet."}</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
      {inspectedId && <section className="panel incident-source-panel" aria-label="Linked security events">
        <div className="detection-header"><h2>Linked security events</h2><button type="button" className="agents-refresh" onClick={() => inspectIncident("")}>Close</button></div>
        {sourceError && <p role="alert">{sourceError}</p>}
        {!sourceError && !sourceEvents && <p role="status">Loading source events…</p>}
        {sourceEvents?.length === 0 && <p>This incident has no linked detection events.</p>}
        {sourceEvents && sourceEvents.length > 0 && <ul className="detection-sources">{sourceEvents.map(event => <li key={event.id}>
          <strong>{event.title}</strong><small>{[event.source, event.source_reference].filter(Boolean).join(" · ")}</small>
          <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
        </li>)}</ul>}
      </section>}
      <footer className="module-footnote">VYRNEXIS AI <span>|</span> Incident records are tenant-scoped by the API session.</footer>
    </div>

    {formOpen && <div className="module-dialog-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setFormOpen(false); }}><section className="module-dialog" role="dialog" aria-modal="true" aria-labelledby="incident-dialog-title"><div className="module-dialog-heading"><div><span className="module-eyebrow">CREATE RECORD</span><h2 id="incident-dialog-title">New incident</h2></div><button className="module-icon-button" aria-label="Close dialog" onClick={() => setFormOpen(false)}><X size={16}/></button></div><form onSubmit={(event) => void createIncident(event)}><label>Incident title<input required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Short, descriptive incident name"/></label><label>Severity<select value={level} onChange={(event) => setLevel(event.target.value)}><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label><label>Description<textarea maxLength={5000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What was observed? Include source references when available." rows={4}/></label><div className="module-dialog-actions"><button className="graph-button" type="button" onClick={() => setFormOpen(false)}>Cancel</button><button className="module-primary" type="submit" disabled={saving}>{saving ? "Saving..." : "Create incident"}</button></div></form></section></div>}
  </main>;
}
