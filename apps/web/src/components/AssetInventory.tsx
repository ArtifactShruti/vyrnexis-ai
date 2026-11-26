"use client";

import { useCallback, useEffect, useState } from "react";
import { Boxes, Plus, RefreshCw, Search, Server, Shield, Workflow } from "lucide-react";

type Asset = {
  id: string;
  name: string;
  asset_type: string;
  identifier: string;
  criticality: "low" | "medium" | "high" | "critical";
  status: "active" | "maintenance" | "retired";
  created_at: string;
  updated_at: string;
};

type AssetDetail = Asset & {
  assignment: { assignee_id: string | null; assignee_name: string | null; team: string; updated_at: string | null };
  vulnerabilities: Array<{ id: string; title: string; cve: string; severity: string; status: string; remediation: string }>;
  history: Array<{ id: string; action: string; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string }>;
};

export default function AssetInventory() {
  const [items, setItems] = useState<Asset[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("server");
  const [identifier, setIdentifier] = useState("");
  const [criticality, setCriticality] = useState<Asset["criticality"]>("medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<AssetDetail | null>(null);
  const [team, setTeam] = useState("");
  const [vulnerabilityTitle, setVulnerabilityTitle] = useState("");
  const [vulnerabilityCve, setVulnerabilityCve] = useState("");
  const [vulnerabilitySeverity, setVulnerabilitySeverity] = useState("medium");

  const load = useCallback(async (query = "", state = "") => {
    setError("");
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("search", query.trim());
      if (state) params.set("status", state);
      const response = await fetch(`/api/assets?${params}`, { cache: "no-store" });
      if (response.status === 401) { window.location.assign("/login"); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Asset records are unavailable.");
      setItems(body);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Asset service is unavailable.");
    }
  }, []);

  useEffect(() => { void load("", ""); }, [load]);

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/assets", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: name.trim(), asset_type: type, identifier: identifier.trim(), criticality }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Asset could not be saved.");
      setName(""); setIdentifier("");
      setMessage(`${body.name} was added to the organization inventory.`);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Asset could not be saved.");
    } finally { setBusy(false); }
  }

  async function openDetail(assetId: string) {
    setError("");
    try {
      const response = await fetch(`/api/workspace/assets/${assetId}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Asset details are unavailable.");
      setSelected(body);
      setTeam(body.assignment?.team || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Asset details are unavailable.");
    }
  }

  async function updateLifecycle(nextStatus: Asset["status"]) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/assets/${selected.id}`, {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Lifecycle update failed.");
      setSelected(body);
      await load(search, status);
      setMessage(`Asset lifecycle changed to ${nextStatus}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Lifecycle update failed.");
    } finally { setBusy(false); }
  }

  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/assets/${selected.id}/assignment`, {
        method: "PUT", headers: { "content-type": "application/json" },
        body: JSON.stringify({ team }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Assignment update failed.");
      setSelected(body);
      setMessage("Asset assignment was persisted.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Assignment update failed.");
    } finally { setBusy(false); }
  }

  async function addVulnerability(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/assets/${selected.id}/vulnerabilities`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: vulnerabilityTitle, cve: vulnerabilityCve, severity: vulnerabilitySeverity }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Vulnerability record could not be saved.");
      setVulnerabilityTitle("");
      setVulnerabilityCve("");
      setVulnerabilitySeverity("medium");
      await openDetail(selected.id);
      setMessage("Vulnerability record was persisted.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Vulnerability record could not be saved.");
    } finally { setBusy(false); }
  }

  return <main className="assets-page">
    <header className="agents-header"><div><div className="agents-kicker">SECURITY / INVENTORY</div><h1>Asset inventory</h1><p>Track organization assets and review their recorded criticality and lifecycle status.</p></div><button className="agents-refresh" onClick={() => void load(search, status)}><RefreshCw size={14}/> Refresh</button></header>
    <div className="assets-notice"><Shield size={16}/><span>Records are scoped to your signed-in organization. Criticality is an analyst supplied label; no vulnerability or risk score is inferred.</span></div>
    {error && <div className="agents-error" role="alert">{error}</div>}{message && <div className="agents-success" role="status">{message}</div>}
    <section className="assets-overview" aria-label="Inventory summary">
      <article><span><Boxes size={16}/></span><div><small>ASSETS IN VIEW</small><strong>{items.length}</strong></div></article>
      <article><span><Shield size={16}/></span><div><small>HIGH / CRITICAL</small><strong>{items.filter(item => item.criticality === "high" || item.criticality === "critical").length}</strong></div></article>
      <article><span><Workflow size={16}/></span><div><small>UNDER MAINTENANCE</small><strong>{items.filter(item => item.status === "maintenance").length}</strong></div></article>
    </section>
    <section className="panel assets-create"><div><div className="agents-kicker">REGISTER ASSET</div><h2>Add to inventory</h2><p>Enter an authorized organization asset. Values are stored as supplied.</p></div><form onSubmit={event => void create(event)}>
      <label htmlFor="asset-name">Asset name</label><input id="asset-name" required minLength={2} maxLength={200} value={name} onChange={event => setName(event.target.value)} placeholder="Example: Finance API cluster"/>
      <label htmlFor="asset-type">Type</label><select id="asset-type" value={type} onChange={event => setType(event.target.value)}><option value="server">Server</option><option value="workstation">Workstation</option><option value="application">Application</option><option value="cloud_resource">Cloud resource</option><option value="network_device">Network device</option><option value="other">Other</option></select>
      <label htmlFor="asset-identifier">Asset identifier</label><input id="asset-identifier" maxLength={200} value={identifier} onChange={event => setIdentifier(event.target.value)} placeholder="Optional CMDB or inventory ID"/>
      <label htmlFor="asset-criticality">Criticality</label><select id="asset-criticality" value={criticality} onChange={event => setCriticality(event.target.value as Asset["criticality"])}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select>
      <button className="agents-run-button" type="submit" disabled={busy || name.trim().length < 2}><Plus size={15}/>{busy ? "Saving…" : "Add asset"}</button>
    </form></section>
    <section className="assets-list"><div className="agent-history-title"><div><div className="agents-kicker">TENANT RECORDS</div><h2>Organization assets</h2></div><span>{items.length} loaded · maximum 500</span></div>
      <div className="assets-toolbar"><form className="assets-search" onSubmit={event => { event.preventDefault(); void load(search, status); }}><Search size={14}/><input aria-label="Search assets" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search name, type, or identifier"/><button type="submit">Search</button></form><label className="assets-status">Status<select value={status} onChange={event => { setStatus(event.target.value); void load(search, event.target.value); }}><option value="">All statuses</option><option value="active">Active</option><option value="maintenance">Maintenance</option><option value="retired">Retired</option></select></label></div>
      {items.length ? <div className="assets-table-wrap"><table className="assets-table"><thead><tr><th>ASSET</th><th>TYPE</th><th>IDENTIFIER</th><th>CRITICALITY</th><th>STATUS</th><th>UPDATED</th><th>ACTIONS</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><strong><Server size={14}/>{item.name}</strong><small>{item.id}</small></td><td>{item.asset_type.replaceAll("_", " ")}</td><td>{item.identifier || "—"}</td><td><span className={`asset-criticality ${item.criticality}`}>{item.criticality}</span></td><td><span className={`asset-state ${item.status}`}>{item.status.replaceAll("_", " ")}</span></td><td>{new Date(item.updated_at).toLocaleString()}</td><td><button className="outline-button" type="button" onClick={() => void openDetail(item.id)}>Inspect</button></td></tr>)}</tbody></table></div> : <div className="agent-empty">{search || status ? "No assets match these filters." : "No assets are recorded for this organization yet."}</div>}
    </section>
    {selected && <section className="panel asset-inspector" aria-label="Selected asset inspector">
      <div className="panel-heading"><div><div className="agents-kicker">ASSET INSPECTOR</div><h2>{selected.name}</h2></div><button className="outline-button" type="button" onClick={() => setSelected(null)}>Close</button></div>
      <div className="asset-inspector-grid">
        <div>
          <label>Lifecycle status<select value={selected.status} onChange={event => void updateLifecycle(event.target.value as Asset["status"])}><option value="active">Active</option><option value="maintenance">Maintenance</option><option value="retired">Retired</option></select></label>
          <form onSubmit={event => void assign(event)} className="asset-team-form"><label>Owner team<input value={team} onChange={event => setTeam(event.target.value)} maxLength={120} placeholder="Unassigned"/></label><button className="primary-button" type="submit" disabled={busy}>Save assignment</button></form>
        </div>
        <div>
          <h3>Vulnerability records</h3>
          {selected.vulnerabilities.length ? <div className="asset-vulnerability-list">{selected.vulnerabilities.map(vulnerability => <article key={vulnerability.id}><strong>{vulnerability.title}</strong><span>{vulnerability.cve || "No CVE"} · {vulnerability.severity} · {vulnerability.status}</span></article>)}</div> : <p className="muted-cell">No vulnerabilities have been recorded.</p>}
          <form onSubmit={event => void addVulnerability(event)} className="asset-vulnerability-form"><input required value={vulnerabilityTitle} onChange={event => setVulnerabilityTitle(event.target.value)} placeholder="Finding title"/><input value={vulnerabilityCve} onChange={event => setVulnerabilityCve(event.target.value)} placeholder="CVE identifier"/><select value={vulnerabilitySeverity} onChange={event => setVulnerabilitySeverity(event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select><button className="primary-button" type="submit" disabled={busy}>Record finding</button></form>
        </div>
        <div>
          <h3>Change history</h3>
          {selected.history.length ? <div className="asset-history-list">{selected.history.map(entry => <article key={entry.id}><strong>{entry.action}</strong><span>{new Date(entry.created_at).toLocaleString()}</span></article>)}</div> : <p className="muted-cell">No lifecycle changes recorded.</p>}
        </div>
      </div>
    </section>}
  </main>;
}
