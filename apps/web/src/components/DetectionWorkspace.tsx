"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

const kinds = {
  failed_signins: "Repeated failed sign-ins",
  unfamiliar_device: "Unfamiliar device",
} as const;

type Kind = keyof typeof kinds;
type Severity = "low" | "medium" | "high" | "critical";
type Rule = { kind: Kind; enabled: boolean; severity: Severity; window_minutes: number; threshold: number };
type Alert = {
  id: string; title: string; severity: Severity; explanation: string;
  status: "open" | "confirmed" | "false_positive"; incident_id: string | null; incident_status: string | null;
  graph_entity_id: string | null;
};
type Run = { id: string; kind: Kind; alert_id: string | null; explanation: string; created_at: string };
type Source = {
  id: string; title: string; source: string; source_reference: string; occurred_at: string;
  account: string | null; device: string | null; outcome: string | null;
};
type Status = { mode: string; worker_available: boolean | null; queued: number; completed: number; failed: number };

const defaults = { enabled: true, severity: "high" as Severity, window_minutes: 15, threshold: 3 };
const labels = { open: "Open", confirmed: "Confirmed", false_positive: "False positive" };

async function detectionRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/detection/${path}`, { cache: "no-store", ...init });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Invalid detection request.");
  return body;
}

export default function DetectionWorkspace({ canWrite, canManageRules }: {
  canWrite: boolean;
  canManageRules: boolean;
}) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [filter, setFilter] = useState<"all" | Alert["status"]>("all");
  const [kind, setKind] = useState<Kind>("failed_signins");
  const [draft, setDraft] = useState(defaults);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const options = { signal };
      const [currentRules, currentAlerts, currentRuns, currentStatus] = await Promise.all([
        detectionRequest<Rule[]>("rules", options), detectionRequest<Alert[]>("alerts", options),
        detectionRequest<Run[]>("runs?limit=20", options), detectionRequest<Status>("status", options),
      ]);
      if (signal?.aborted) return;
      setRules(currentRules);
      setAlerts(currentAlerts);
      setRuns(currentRuns);
      setStatus(currentStatus);
      setSelected(previous => previous && currentAlerts.some(alert => alert.id === previous) ? previous : null);
      setError("");
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause.message : "Could not refresh detection records.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh(controller.signal);
    }, 15000);
    return () => { controller.abort(); window.clearInterval(interval); };
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    detectionRequest<Source[]>(`alerts/${encodeURIComponent(selected)}/events`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setSources(result); })
      .catch(cause => { if (!controller.signal.aborted) setSourceError(cause.message); });
    return () => controller.abort();
  }, [selected]);

  const current = alerts.find(alert => alert.id === selected);
  const visible = alerts.filter(alert => filter === "all" || alert.status === filter);

  function selectAlert(id: string) {
    if (selected === id) return;
    setSources(null);
    setSourceError("");
    setNote("");
    setSelected(id);
  }

  function loadRule(next: Kind) {
    const saved = rules.find(rule => rule.kind === next);
    setKind(next);
    setDraft(saved ? {
      enabled: saved.enabled, severity: saved.severity, window_minutes: saved.window_minutes, threshold: saved.threshold,
    } : defaults);
  }

  async function saveRule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await detectionRequest<Rule>(`rules/${kind}`, { method: "PUT", body: JSON.stringify(draft) });
      await refresh();
      setMessage(`${kinds[kind]} settings saved.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save the detection rule.");
    } finally {
      setBusy(false);
    }
  }

  async function resolveAlert(action: "incident" | "false-positive") {
    if (!current) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const alert = await detectionRequest<Alert>(`alerts/${current.id}/${action}`, {
        method: "POST", body: action === "false-positive" ? JSON.stringify({ note: note.trim() }) : undefined,
      });
      setAlerts(previous => previous.map(item => item.id === alert.id ? alert : item));
      setMessage(action === "incident" ? "Incident created with its source events." : "False-positive feedback saved.");
      setNote("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not resolve the alert.");
    } finally {
      setBusy(false);
    }
  }

  return <section className="detection-workspace" aria-labelledby="detection-heading">
    <div className="detection-header">
      <h2 id="detection-heading">Detection and triage</h2>
      <button className="agents-refresh" type="button" onClick={() => void refresh()} disabled={busy}>Refresh detections</button>
    </div>
    {status && <p className="detection-status">
      {status.mode === "worker" ? (status.worker_available ? "Detection worker ready" : "Detection worker unavailable") : "Inline detection"}
      {" · "}{status.completed} processed · {status.queued} queued · {status.failed} failed
    </p>}
    {error && <p className="agents-error" role="alert">{error}</p>}
    {message && <p className="agents-success" role="status">{message}</p>}
    <div className="detection-grid">
      <aside className="panel detection-panel" aria-label="Detection rules">
        <h3>Rules</h3>
        {rules.length ? <ul className="detection-rule-list">{rules.map(rule => <li key={rule.kind}>
          <strong>{kinds[rule.kind]}</strong><small>{rule.enabled ? "Enabled" : "Disabled"} · {rule.window_minutes} min · {rule.severity}</small>
        </li>)}</ul> : <p>{loading ? "Loading rules…" : "No rules configured."}</p>}
        {canManageRules && <form className="detection-form" onSubmit={event => void saveRule(event)}>
          <label>Rule<select value={kind} onChange={event => loadRule(event.target.value as Kind)}>
            {Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <button className="agents-refresh" type="button" disabled={!rules.some(rule => rule.kind === kind)} onClick={() => loadRule(kind)}>Load saved settings</button>
          <label>Severity<select value={draft.severity} onChange={event => setDraft({ ...draft, severity: event.target.value as Severity })}>
            {["low", "medium", "high", "critical"].map(level => <option key={level}>{level}</option>)}
          </select></label>
          <label>Look-back (minutes)<input type="number" min="1" max="1440" required value={draft.window_minutes || ""} onChange={event => setDraft({ ...draft, window_minutes: Number(event.target.value) })}/></label>
          {kind === "failed_signins" && <label>Failure threshold<input type="number" min="2" max="100" required value={draft.threshold || ""} onChange={event => setDraft({ ...draft, threshold: Number(event.target.value) })}/></label>}
          <label className="detection-checkbox"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft({ ...draft, enabled: event.target.checked })}/> Enable rule</label>
          <button className="primary-button" disabled={busy}>Save rule</button>
        </form>}
      </aside>
      <section className="panel detection-panel" aria-labelledby="alert-heading">
        <h3 id="alert-heading">Analyst review queue</h3>
        <label className="detection-filter">Alert status<select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}>
          <option value="all">All statuses</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <div className="detection-severities" aria-label="Severity distribution of loaded alerts">
          {(["critical", "high", "medium", "low"] as const).map(level => {
            const count = visible.filter(alert => alert.severity === level).length;
            return <div key={level}><span>{level}</span><meter aria-label={`${level} alerts`} min={0} max={Math.max(1, visible.length)} value={count}/><strong>{count}</strong></div>;
          })}
        </div>
        <div className="detection-alerts">
          {visible.map(alert => <button key={alert.id} type="button" aria-pressed={selected === alert.id} onClick={() => selectAlert(alert.id)}>
            <strong>{alert.title}</strong><span>{alert.severity} · {labels[alert.status]}</span>
          </button>)}
          {!visible.length && !error && <p>{loading ? "Loading alerts…" : "No alerts match the current view."}</p>}
        </div>
        {runs.length > 0 && <details className="detection-history"><summary>Recent rule executions ({runs.length})</summary>
          <ul>{runs.map(run => <li key={run.id}><strong>{kinds[run.kind]} · {run.alert_id ? "Matched" : "No match"}</strong>
            <small>{run.explanation}</small><time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></li>)}</ul>
        </details>}
      </section>
      <aside className="panel detection-panel" aria-label="Alert details">
        <h3>Alert details</h3>
        {!current ? <p>Select an alert to inspect its source events.</p> : <>
          <h4>{current.title}</h4><p>{current.explanation} This correlation does not establish causation.</p>
          {current.incident_id && <Link className="subtle-link" href={`/platform/incidents?id=${encodeURIComponent(current.incident_id)}`}>Open incident · {current.incident_status}</Link>}
          {current.graph_entity_id && <Link className="subtle-link" href={`/platform/graph?focus=${encodeURIComponent(current.graph_entity_id)}`}>Explore linked graph</Link>}
          {sourceError && <p role="alert">{sourceError}</p>}
          {!sources && !sourceError && <p role="status">Loading source events…</p>}
          {sources && <ul className="detection-sources">{sources.map(source => <li key={source.id}>
            <strong>{source.title}</strong><small>{[source.source, source.source_reference, source.account, source.device, source.outcome].filter(Boolean).join(" · ")}</small>
            <time dateTime={source.occurred_at}>{new Date(source.occurred_at).toLocaleString()}</time>
          </li>)}</ul>}
          {canWrite && current.status === "open" && <div className="detection-form">
            <button className="primary-button" type="button" onClick={() => void resolveAlert("incident")} disabled={busy || !sources?.length}>Confirm and create incident</button>
            <label>False-positive reason<textarea value={note} maxLength={1000} rows={3} onChange={event => setNote(event.target.value)}/></label>
            <button className="agents-refresh" type="button" disabled={busy || note.trim().length < 3} onClick={() => void resolveAlert("false-positive")}>Mark false positive</button>
          </div>}
        </>}
      </aside>
    </div>
  </section>;
}
