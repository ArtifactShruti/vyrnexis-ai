"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, RefreshCw, Server } from "lucide-react";
import { workspace } from "@/lib/ai-workspace";

type Status = {
  measured_at: string;
  api: { status: string; database_probe_latency_ms: number };
  database: { status: string; dialect: string };
  redis: { status: string };
  worker: { status: string };
  queues: { detection_jobs: number };
  executions: { agents: Record<string, number>; workflows: Record<string, number>; investigations: Record<string, number>; reports: Record<string, number> };
  ingestion: { batches_with_rejections: number };
  limitations: string[];
};

export default function ObservabilityWorkspace() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { setStatus(await workspace<Status>("observability/status")); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Operational health is unavailable."); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const statusClass = (value: string) => ["connected", "healthy"].includes(value) ? "success" : "warning";
  return <main className="module-page observability-page">
    <header className="module-heading"><div><div className="eyebrow">SYSTEM OPERATIONS</div><h1>Observability</h1><p>Live, tenant-authorized infrastructure probes and persisted execution counts.</p></div><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button></header>
    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Health probe failed</strong><span>{error}</span></div></div>}
    {status && <>
      <section className="module-stat-grid">
        {[["API", status.api.status, `${status.api.database_probe_latency_ms} ms database probe`], ["Database", status.database.status, status.database.dialect], ["Redis", status.redis.status, "Current ping"], ["Worker", status.worker.status, "Latest heartbeat probe"], ["Detection queue", String(status.queues.detection_jobs), "Persisted queued/running jobs"], ["Ingestion failures", String(status.ingestion.batches_with_rejections), "Batches containing rejected rows"]].map(([label, value, note]) => <article className="metric-card" key={label}><div className="metric-top"><span>{label}</span><Server size={15}/></div><div className={`metric-number ${statusClass(String(value))}`}>{value}</div><small>{note}</small></article>)}
      </section>
      <section className="observability-grid">
        {[
          { title: "Agent executions", values: status.executions.agents },
          { title: "Workflow executions", values: status.executions.workflows },
          { title: "Nexus investigations", values: status.executions.investigations },
          { title: "Report snapshots", values: status.executions.reports },
        ].map(({ title, values }) => <article className="panel" key={title}><div className="panel-heading"><div><div className="panel-kicker">PERSISTED COUNTS</div><h2>{title}</h2></div><Activity size={15}/></div><div className="observability-statuses">{Object.entries(values).length ? Object.entries(values).map(([state, count]) => <div key={state}><span>{state}</span><strong>{count}</strong></div>) : <p>No persisted records</p>}</div></article>)}
      </section>
      <section className="panel observability-note"><h2>Measurement limitations</h2>{status.limitations.map((line) => <p key={line}>{line}</p>)}</section>
    </>}
  </main>;
}
