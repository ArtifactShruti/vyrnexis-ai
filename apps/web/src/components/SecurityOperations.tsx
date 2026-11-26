"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, FilePlus2, RefreshCw, Search, ShieldAlert } from "lucide-react";
import DetectionWorkspace from "./DetectionWorkspace";

type EventRecord = {
  id: string;
  source: string;
  event_type: string;
  severity: "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  source_reference: string;
  status: "new" | "reviewed" | "dismissed";
  occurred_at: string;
  received_at: string;
};

export default function SecurityOperations() {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [canWrite, setCanWrite] = useState(false);
  const [canManageRules, setCanManageRules] = useState(false);
  const requestId = useRef(0);
  const [source, setSource] = useState("");
  const [eventType, setEventType] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [reference, setReference] = useState("");
  const [externalId, setExternalId] = useState("");
  const [account, setAccount] = useState("");
  const [device, setDevice] = useState("");
  const [outcome, setOutcome] = useState("");
  const [newSeverity, setNewSeverity] = useState<EventRecord["severity"]>("medium");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async (query = "", level = "", reviewStatus = "", signal?: AbortSignal) => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("search", query.trim());
      if (level) params.set("severity", level);
      if (reviewStatus) params.set("status", reviewStatus);
      const response = await fetch(`/api/security-events?${params}`, { cache: "no-store", signal });
      if (signal?.aborted || id !== requestId.current) return;
      if (response.status === 401) { window.location.assign("/login"); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Security events are unavailable.");
      if (!signal?.aborted && id === requestId.current) setEvents(body);
    } catch (cause) {
      if (!signal?.aborted && id === requestId.current) setError(cause instanceof Error ? cause.message : "Security event service is unavailable.");
    } finally {
      if (!signal?.aborted && id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load("", "", "", controller.signal);
    fetch("/api/auth/session", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) return;
        const identity = await response.json();
        if (!controller.signal.aborted) {
          setCanWrite(["owner", "organization_admin", "security_analyst", "forensic_investigator"].includes(identity.user.role));
          setCanManageRules(["owner", "organization_admin", "security_analyst"].includes(identity.user.role));
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [load]);

  async function ingest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/security-events", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          source: source.trim(), event_type: eventType.trim(), title: title.trim(), description: description.trim(),
          source_reference: reference.trim(), severity: newSeverity,
          external_id: externalId.trim() || null,
          account: account.trim() || null, device: device.trim() || null,
          outcome: isAuthentication ? outcome || null : null,
        }),
      });
      if (response.status === 401) { window.location.assign("/login"); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Security event could not be recorded.");
      setTitle(""); setDescription(""); setReference(""); setExternalId("");
      setMessage(`${body.title} was recorded for analyst review.`);
      await load(search, severity, status);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Security event could not be recorded.");
    } finally { setBusy(false); }
  }

  async function review(item: EventRecord, next: "reviewed" | "dismissed") {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch(`/api/security-events/${encodeURIComponent(item.id)}/status`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      if (response.status === 401) { window.location.assign("/login"); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Review could not be saved.");
      setMessage(`${item.title} marked as ${next}.`);
      await load(search, severity, status);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Review could not be saved.");
    } finally { setBusy(false); }
  }

  const isAuthentication = ["authentication", "login", "sign_in"].includes(eventType.trim().toLowerCase());

  return <main className="security-page">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="agents-header"><div><h1>Security operations</h1><p>Record and triage organization security events.</p></div><button className="agents-refresh" disabled={loading || busy} onClick={() => void load(search, severity, status)}><RefreshCw size={14}/> Refresh</button></header>
    <div className="security-notice"><ShieldAlert size={16}/><span>Rules evaluate events submitted by authorized sources. The workspace has no connected external telemetry feed.</span></div>
    {error && <div className="agents-error" role="alert">{error}</div>}{message && <div className="agents-success" role="status">{message}</div>}
    <section className="security-summary" aria-label="Event summary"><article><Activity size={16}/><div><small>EVENTS IN VIEW</small><strong>{events.length}</strong></div></article><article><AlertTriangle size={16}/><div><small>HIGH / CRITICAL</small><strong>{events.filter(item => item.severity === "high" || item.severity === "critical").length}</strong></div></article><article><span className="security-new-dot"/><div><small>AWAITING REVIEW</small><strong>{events.filter(item => item.status === "new").length}</strong></div></article></section>
    <DetectionWorkspace canWrite={canWrite} canManageRules={canManageRules}/>
    {canWrite && <section className="panel security-ingest"><div><h2>Record a security event</h2><p>Enter an event from an authorized source. Use the same source event ID when retrying a submission.</p></div><form onSubmit={event => void ingest(event)}>
      <label htmlFor="security-title">Event title</label><input id="security-title" required minLength={3} maxLength={240} value={title} onChange={event => setTitle(event.target.value)} placeholder="Describe the observed event"/>
      <label htmlFor="security-source">Source</label><input id="security-source" required minLength={2} maxLength={120} value={source} onChange={event => setSource(event.target.value)} placeholder="Authorized log or system name"/>
      <label htmlFor="security-type">Event type</label><input id="security-type" required minLength={2} maxLength={120} value={eventType} onChange={event => setEventType(event.target.value)} placeholder="authentication_anomaly"/>
      <label htmlFor="security-severity">Severity</label><select id="security-severity" value={newSeverity} onChange={event => setNewSeverity(event.target.value as EventRecord["severity"])}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select>
      <label htmlFor="security-reference">Source reference</label><input id="security-reference" maxLength={240} value={reference} onChange={event => setReference(event.target.value)} placeholder="Optional source record ID"/>
      <label htmlFor="security-event-id">Source event ID</label><input id="security-event-id" maxLength={200} value={externalId} onChange={event => setExternalId(event.target.value)} placeholder="Optional deduplication key"/>
      {isAuthentication && <>
        <label htmlFor="security-account">Account label</label><input id="security-account" maxLength={200} value={account} onChange={event => setAccount(event.target.value)} required={Boolean(outcome)}/>
        <label htmlFor="security-device">Device label</label><input id="security-device" maxLength={200} value={device} onChange={event => setDevice(event.target.value)}/>
        <label htmlFor="security-outcome">Outcome</label><select id="security-outcome" value={outcome} onChange={event => setOutcome(event.target.value)}><option value="">Unspecified</option><option value="success">Success</option><option value="failure">Failure</option></select>
      </>}
      <label htmlFor="security-description">Analyst context</label><textarea id="security-description" maxLength={4000} value={description} onChange={event => setDescription(event.target.value)} placeholder="Optional observations and context"/>
      <button className="agents-run-button" type="submit" disabled={busy || title.trim().length < 3 || source.trim().length < 2 || eventType.trim().length < 2}><FilePlus2 size={15}/>{busy ? "Recording…" : "Record event"}</button>
    </form></section>}
    <section className="security-events" aria-busy={loading}>
      <div className="agent-history-title"><h2>Event stream</h2><span>{events.length} loaded · maximum 100</span></div>
      <div className="security-toolbar">
        <form className="assets-search" onSubmit={event => { event.preventDefault(); void load(search, severity, status); }}>
          <Search size={14}/><input aria-label="Search security events" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Search title, event type, or source reference"/><button type="submit">Search</button>
        </form>
        <label className="assets-status">Severity<select value={severity} onChange={event => { setSeverity(event.target.value); void load(search, event.target.value, status); }}><option value="">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
        <label className="assets-status">Review status<select value={status} onChange={event => { setStatus(event.target.value); void load(search, severity, event.target.value); }}><option value="">All statuses</option><option value="new">New</option><option value="reviewed">Reviewed</option><option value="dismissed">Dismissed</option></select></label>
      </div>
      {loading ? <p className="agent-empty" role="status">Loading security events…</p> : events.length ? (
        <div className="security-event-list">{events.map(item => (
          <article className="security-event" key={item.id}>
            <span className={`security-event-icon ${item.severity}`}><AlertTriangle size={15}/></span>
            <div className="security-event-content">
              <div className="security-event-head"><strong>{item.title}</strong><span className={`asset-criticality ${item.severity}`}>{item.severity}</span></div>
              {item.description && <p>{item.description}</p>}
              <div className="security-event-details">
                <span>{item.source} · {item.event_type.replaceAll("_", " ")}</span>
                {item.source_reference && <span>{item.source_reference}</span>}
                <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString()}</time><b>{item.status}</b>
              </div>
              {canWrite && item.status === "new" && (
                <div className="security-review-actions">
                  <button className="agents-refresh" disabled={busy} onClick={() => void review(item, "reviewed")}>Mark reviewed</button>
                  <button className="agents-refresh" disabled={busy} onClick={() => void review(item, "dismissed")}>Dismiss</button>
                </div>
              )}
            </div>
          </article>
        ))}</div>
      ) : !error && <div className="agent-empty">No security events match the current view.</div>}
    </section>
  </main>;
}
