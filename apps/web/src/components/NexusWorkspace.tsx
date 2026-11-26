"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { caseWriters, forensic, forensicBody, localTime, sessionRole } from "@/lib/forensic";
import NexusInterpretations from "@/components/NexusInterpretations";

type Context = { id: string; title: string };
type Run = { id: string; status: string; case_id: string | null; incident_id: string | null; updated_at: string; review_note: string | null };
type Finding = { agent: string; claim: string; verification_status: string; limitations: string[]; sources: string[]; evidence_refs: string[]; alternative_explanations: string[]; risk_factors: string[] };
type Task = {
  id: string; agent: string; status: string; attempts: number; dependencies: string[]; result: Finding | null; error: string | null;
  history: { number: number; status: string; started_at: string; finished_at: string | null; error: string | null }[];
};
type Detail = Run & { tasks: Task[]; replay: { source_run_id: string; target_agents: string[] | null } | null };
type Worker = { mode: string; worker_available: boolean | null };
const lanes = [["SENTINEL", "MERCURY", "TRACE", "ORACLE"], ["VERITAS"], ["AEGIS"], ["NEXUS"]];
const label = (value: string) => value.replaceAll("_", " ");

export default function NexusWorkspace() {
  const [cases, setCases] = useState<Context[]>([]);
  const [incidents, setIncidents] = useState<Context[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [worker, setWorker] = useState<Worker | null>(null);
  const [role, setRole] = useState("");
  const [kind, setKind] = useState("case");
  const [contextId, setContextId] = useState("");
  const [selected, setSelected] = useState("");
  const [taskId, setTaskId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [note, setNote] = useState("");
  const [requestKey, setRequestKey] = useState("");
  const [agent, setAgent] = useState("");
  const [comparison, setComparison] = useState<Detail>();
  const [replayKey, setReplayKey] = useState<{ target: string; value: string }>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const task = detail?.tasks.find(item => item.id === taskId);
  const active = detail && ["queued", "running"].includes(detail.status);
  const replayable = (status: string) => ["failed", "timed_out"].includes(status);
  const canReplay = detail && !active && caseWriters.includes(role) && detail.tasks.some(item => replayable(item.status));

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [history, health] = await Promise.all([
      forensic<Run[]>("investigations", { signal }),
      forensic<Worker>("investigations/worker", { signal }),
    ]);
    if (!signal?.aborted) { setRuns(history); setWorker(health); }
  }, []);
  const loadRun = useCallback(async (id: string, signal?: AbortSignal) => {
    const data = await forensic<Detail>(`investigations/${id}`, { signal });
    if (!signal?.aborted) setDetail(data);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(window.location.search);
    if (params.has("case")) setContextId(params.get("case") || "");
    if (params.has("incident")) { setKind("incident"); setContextId(params.get("incident") || ""); }
    const signal = controller.signal;
    void Promise.all([refresh(signal), sessionRole(signal), forensic<{ items: Context[] }>("forensic-cases?limit=100", { signal }),
      fetch("/api/incidents", { signal, cache: "no-store" }).then(async response => response.ok ? await response.json() : [])])
      .then(([, userRole, records, incidentRows]) => { if (!signal.aborted) { setRole(userRole); setCases(records.items); setIncidents(incidentRows); } })
      .catch(cause => { if (!signal.aborted) setError(cause.message); }).finally(() => { if (!signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    let fetching = false;
    async function update() {
      if (fetching) return;
      fetching = true;
      try { await Promise.all([loadRun(selected, controller.signal), refresh(controller.signal)]); }
      catch (cause) { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Run status unavailable."); }
      finally { fetching = false; }
    }
    void update();
    const timer = window.setInterval(() => { if (!document.hidden) void update(); }, 4000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [selected, loadRun, refresh]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Investigation request failed."); }
    finally { setBusy(false); }
  }
  function choose(id: string) {
    if (selected !== id) { setSelected(id); setTaskId(""); setDetail(null); setComparison(undefined); setReplayKey(undefined); }
  }

  async function replay(target?: string) {
    if (!detail) return;
    const keyTarget = `${detail.id}:${target || "all"}`;
    const key = replayKey?.target === keyTarget ? replayKey.value : crypto.randomUUID();
    setReplayKey({ target: keyTarget, value: key });
    const run = await forensic<Detail>(`investigations/${detail.id}/replay`,
      forensicBody("POST", { request_key: key, ...(target ? { agents: [target] } : {}) }));
    choose(run.id); setDetail(run); await refresh(); setMessage("Replay submitted as a new investigation.");
  }

  return <main className="intake-page investigation-case">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Investigation Nexus</h1><p>Run seven deterministic analyses over an authorized case or incident, then review the recorded findings.</p></div>
      <div className="intake-actions"><Link className="agents-refresh" href="/platform/forensics">Forensic cases</Link><Link className="agents-refresh" href="/platform/agents">Agent history</Link></div>
    </header>
    {worker && <p className="nexus-health">{worker.mode === "inline" ? "SQLite inline execution" : worker.worker_available ? "Worker heartbeat available" : "Worker heartbeat unavailable"}</p>}
    {loading && <p role="status">Loading investigation context…</p>}
    {error && <p className="agents-error" role="alert">{error}</p>}
    {message && <p className="agents-success" role="status">{message}</p>}
    <div className="intake-layout nexus-layout">
      <aside className="panel intake-panel" aria-label="Investigation context">
        <h2>Start an investigation</h2>
        <form className="detection-form" onSubmit={event => {
          event.preventDefault();
          void act(async () => {
            const key = requestKey || crypto.randomUUID(); setRequestKey(key);
            const run = await forensic<Detail>("investigations", forensicBody("POST", { [`${kind}_id`]: contextId, request_key: key, ...(agent ? { agents: [agent] } : {}) }));
            choose(run.id); setDetail(run); setRequestKey(""); await refresh(); setMessage("Investigation submitted.");
          });
        }}>
          <label>Context type<select value={kind} onChange={event => { setKind(event.target.value); setContextId(""); setRequestKey(""); }}><option value="case">Forensic case</option><option value="incident">Incident</option></select></label>
          <label>Investigation target<select value={contextId} required onChange={event => { setContextId(event.target.value); setRequestKey(""); }}><option value="">Choose a record</option>
            {(kind === "case" ? cases : incidents).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <label>Agents<select value={agent} onChange={event => { setAgent(event.target.value); setRequestKey(""); }}><option value="">Full pipeline</option>
            {lanes.flat().map(item => <option key={item} value={item}>{item} and prerequisites</option>)}</select></label>
          <button className="primary-button" disabled={busy || !contextId || !role}>Start analysis</button>
        </form>
        <h3>Recent investigations</h3>
        <div className="intake-list">{runs.map(run => <button key={run.id} type="button" disabled={busy} aria-pressed={run.id === selected} onClick={() => choose(run.id)}>
          <strong>{label(run.status)}</strong><small>{run.case_id ? cases.find(item => item.id === run.case_id)?.title || run.case_id : incidents.find(item => item.id === run.incident_id)?.title || run.incident_id}</small>
          <small>{localTime(run.updated_at)}</small></button>)}</div>
        {!runs.length && !loading && !error && <p>No runs have been submitted.</p>}
      </aside>
      <section className="panel intake-panel" aria-label="Execution graph">
        <h2>Agent dependencies</h2>
        {!detail && <p>{selected && !error ? "Loading investigation…" : "Select a run to see its task dependencies."}</p>}
        {detail && <>
          <p aria-live="polite">Run status · {label(detail.status)}</p>
          {detail.replay && <div className="intake-actions"><button className="agents-refresh" type="button" disabled={busy}
            onClick={() => void act(async () => { setComparison(await forensic<Detail>(`investigations/${detail.replay?.source_run_id}`)); })}>Compare with original</button></div>}
          {comparison && <details className="detection-history" open><summary>Original and replay task status</summary>
            <ul className="detection-sources">{detail.tasks.map(item => <li key={item.id}><strong>{item.agent}</strong><small>
              {label(comparison.tasks.find(previous => previous.agent === item.agent)?.status || "not_run")} → {label(item.status)}</small></li>)}</ul>
          </details>}
          <div className="nexus-lanes">{lanes.map((lane, index) => <section key={lane[0]} aria-label={["Source analysis", "Verification", "Governance", "Aggregation"][index]}>
            <h3>{["Source analysis", "Verification", "Governance", "Aggregation"][index]}</h3>
            <div className="intake-list">{lane.map(agent => {
              const item = detail.tasks.find(row => row.agent === agent);
              if (!item) return null;
              return <button type="button" key={item.id} aria-pressed={item.id === taskId} onClick={() => setTaskId(item.id)}>
                <strong>{agent}</strong><small className="nexus-state">{label(item.status)} · {item.attempts} attempts</small>
                {!!item.dependencies.length && <small>After {item.dependencies.map(id => detail.tasks.find(row => row.id === id)?.agent).join(", ")}</small>}
              </button>;
            })}</div>
          </section>)}</div>
          {active && <button className="agents-refresh" type="button" disabled={busy} onClick={() => void act(async () => {
            const next = await forensic<Detail>(`investigations/${detail.id}/cancel`, { method: "POST" }); setDetail(next); await refresh();
          })}>Cancel run</button>}
          {canReplay && <button className="agents-refresh" type="button" disabled={busy} onClick={() => void act(() => replay())}>Replay original plan</button>}
          {["awaiting_approval", "approved", "rejected"].includes(detail.status) && <div className="intake-actions">
            <a className="agents-refresh" href={`/api/forensic/investigations/${detail.id}/report`}>Export report JSON</a>
          </div>}
          {detail.status === "awaiting_approval" && caseWriters.includes(role) && <form className="detection-form" onSubmit={event => {
            event.preventDefault(); const data = new FormData(event.currentTarget);
            void act(async () => {
              const next = await forensic<Detail>(`investigations/${detail.id}/review`, forensicBody("POST", { decision: data.get("decision"), note: note.trim() }));
              setDetail(next); setNote(""); await refresh(); setMessage("Human review recorded.");
            });
          }}>
            <label>Review decision<select name="decision"><option value="approved">Approve report</option><option value="rejected">Reject report</option></select></label>
            <label>Review note<textarea value={note} onChange={event => setNote(event.target.value)} required minLength={3} maxLength={500} rows={3}/></label>
            <button className="primary-button" disabled={busy}>Save review</button>
          </form>}
          {detail.review_note && <p>Reviewer note · {detail.review_note}</p>}
        </>}
      </section>
      <aside className="panel intake-panel" aria-label="Selected finding">
        <h2>Finding inspector</h2>
        {!task && <p>Select an agent to inspect its result and execution attempts.</p>}
        {task && <>
          <h3>{task.agent}</h3><p>{label(task.status)}</p>{task.error && <p role="alert">{task.error}</p>}
          {canReplay && replayable(task.status) && <button className="agents-refresh" type="button" disabled={busy}
            onClick={() => void act(() => replay(task.agent))}>Replay this task and prerequisites</button>}
          {task.result && <>
            <p><strong>{label(task.result.verification_status)}</strong></p><p>{task.result.claim}</p>
            {[["Sources", task.result.sources], ["Evidence", task.result.evidence_refs], ["Risk factors", task.result.risk_factors],
              ["Limitations", task.result.limitations], ["Alternative explanations", task.result.alternative_explanations]].map(([title, values]) =>
              Array.isArray(values) && values.length > 0 && <details key={String(title)} className="detection-history"><summary>{title} ({values.length})</summary><ul className="detection-sources">{values.map(value => <li key={value}>{value}</li>)}</ul></details>)}
          </>}
          {task.result && detail && <NexusInterpretations key={task.id} runId={detail.id} taskId={task.id} canReview={caseWriters.includes(role)} />}
          <h3>Execution timeline</h3>
          {!task.history.length && <p>No attempts started.</p>}
          <ol className="detection-sources">{task.history.map(item => <li key={item.number}><strong>Attempt {item.number} · {label(item.status)}</strong><small>{localTime(item.started_at)}{item.finished_at ? ` → ${localTime(item.finished_at)}` : ""}</small>{item.error && <small>{item.error}</small>}</li>)}</ol>
        </>}
        {detail && <details className="detection-history"><summary>Compare evidence gaps</summary><ul className="detection-sources">
          {detail.tasks.filter(item => item.result && item.result.verification_status !== "supported_by_records").map(item => <li key={item.id}><strong>{item.agent} · {label(item.result!.verification_status)}</strong><small>{item.result!.claim}</small></li>)}
        </ul></details>}
      </aside>
    </div>
  </main>;
}
