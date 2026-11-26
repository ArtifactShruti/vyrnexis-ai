"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";

type Indicator = {
  id: string;
  indicator_type: "ip" | "domain" | "url" | "hash";
  value: string;
  classification: "unknown" | "benign" | "suspicious" | "malicious";
  confidence: number;
  provenance: string;
  notes: string;
  status: string;
  expires_at: string | null;
  updated_at: string;
};

export default function ThreatWorkspace() {
  const [rows, setRows] = useState<Indicator[]>([]);
  const [selected, setSelected] = useState<(Indicator & { matches: { security_events: unknown[]; assets: unknown[]; incidents: unknown[] } }) | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [dialog, setDialog] = useState(false);
  const [type, setType] = useState<Indicator["indicator_type"]>("ip");
  const [value, setValue] = useState("");
  const [classification, setClassification] = useState<Indicator["classification"]>("unknown");
  const [confidence, setConfidence] = useState(0);
  const [provenance, setProvenance] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/workspace/threat-indicators", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Threat indicators are unavailable.");
      setRows(body);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Threat indicators are unavailable.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => rows.filter((row) => JSON.stringify(row).toLowerCase().includes(query.toLowerCase())),
    [rows, query]);

  const createIndicator = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/workspace/threat-indicators", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ indicator_type: type, value, classification, confidence, provenance, notes }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Indicator could not be saved.");
      setDialog(false);
      setValue("");
      setClassification("unknown");
      setConfidence(0);
      setProvenance("");
      setNotes("");
      setMessage("Indicator was persisted in the organization.");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Indicator could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const inspect = async (id: string) => {
    setError("");
    try {
      const response = await fetch(`/api/workspace/threat-indicators/${id}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Indicator details are unavailable.");
      setSelected(body);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Indicator details are unavailable.");
    }
  };

  return <main className="module-page">
    <header className="module-heading"><div><div className="eyebrow">THREAT INTELLIGENCE</div><h1>Indicators and matching</h1><p>Analyst-supplied indicators matched against persisted tenant records. No indicator is labeled malicious by inference.</p></div><div className="module-actions"><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button><button className="primary-button" type="button" onClick={() => setDialog(true)}><Plus size={15}/>Add indicator</button></div></header>
    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Threat intelligence request failed</strong><span>{error}</span></div></div>}
    {message && <div className="notice success-notice" role="status"><ShieldCheck size={16}/><div><strong>Saved</strong><span>{message}</span></div></div>}
    <section className="panel module-table-panel">
      <div className="table-toolbar"><div className="table-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search indicators, provenance, or classification"/></div><span className="table-count">{visible.length} indicators</span></div>
      {visible.length === 0 ? <div className="module-empty"><ShieldCheck size={21}/><strong>No indicators recorded</strong><span>Authorized analyst indicators will appear here.</span></div> :
        <div className="table-wrap"><table className="module-table"><thead><tr><th>Type</th><th>Value</th><th>Classification</th><th>Confidence</th><th>Status</th><th>Action</th></tr></thead><tbody>{visible.map((row) => <tr key={row.id}><td>{row.indicator_type}</td><td>{row.value}</td><td>{row.classification}</td><td>{row.confidence}/100</td><td>{row.status}</td><td><button className="outline-button" type="button" onClick={() => void inspect(row.id)}>Inspect</button></td></tr>)}</tbody></table></div>}
    </section>
    {selected && <section className="panel threat-inspector"><div className="panel-heading"><div><div className="panel-kicker">MATCH INSPECTOR</div><h2>{selected.value}</h2></div><button className="outline-button" type="button" onClick={() => setSelected(null)}>Close</button></div><p><strong>Classification:</strong> {selected.classification} · <strong>Confidence:</strong> {selected.confidence}/100 · <strong>Provenance:</strong> {selected.provenance || "Not recorded"}</p><p>{selected.notes || "No analyst notes recorded."}</p><div className="threat-match-grid"><article><h3>Security events</h3><strong>{selected.matches.security_events.length}</strong></article><article><h3>Assets</h3><strong>{selected.matches.assets.length}</strong></article><article><h3>Incidents</h3><strong>{selected.matches.incidents.length}</strong></article></div></section>}
    {dialog && <div className="module-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(false); }}><form className="module-dialog" onSubmit={createIndicator}><div className="panel-heading"><div><div className="panel-kicker">NEW INDICATOR</div><h2>Add tenant indicator</h2></div><button type="button" className="icon-button" onClick={() => setDialog(false)}>×</button></div><label>Indicator type<select value={type} onChange={(event) => setType(event.target.value as Indicator["indicator_type"])}><option value="ip">IP address</option><option value="domain">Domain</option><option value="url">URL</option><option value="hash">File hash</option></select></label><label>Value<input required minLength={2} maxLength={300} value={value} onChange={(event) => setValue(event.target.value)}/></label><label>Classification<select value={classification} onChange={(event) => setClassification(event.target.value as Indicator["classification"])}><option value="unknown">Unknown</option><option value="benign">Benign</option><option value="suspicious">Suspicious</option><option value="malicious">Malicious</option></select></label><label>Confidence<input type="range" min={0} max={100} value={confidence} onChange={(event) => setConfidence(Number(event.target.value))}/><span>{confidence}/100</span></label><label>Provenance<input maxLength={300} value={provenance} onChange={(event) => setProvenance(event.target.value)} placeholder="Source or reference"/></label><label>Analyst notes<textarea maxLength={4000} value={notes} onChange={(event) => setNotes(event.target.value)} rows={4}/></label><button className="primary-button" type="submit" disabled={busy}>Save indicator</button></form></div>}
  </main>;
}
