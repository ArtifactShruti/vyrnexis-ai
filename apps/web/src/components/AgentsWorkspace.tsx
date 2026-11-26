"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Bot, CircleAlert, Clock3, Play, RefreshCw, ShieldCheck } from "lucide-react";

type Agent = { name: string; responsibility: string; status: string; human_approval_required: boolean; provider_configured: boolean };
type Execution = { id: string; agent: string; task_type: string; status: string; created_at: string; output: { finding: string; evidence: string[]; confidence: number | null; recommended_action: string; limitations: string[]; requires_approval: boolean } };

export default function AgentsWorkspace() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [history, setHistory] = useState<Execution[]>([]);
  const [selected, setSelected] = useState("SENTINEL");
  const [incidentId, setIncidentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [registry, runs] = await Promise.all([
        fetch("/api/agents", { cache: "no-store" }),
        fetch("/api/agents?view=history", { cache: "no-store" }),
      ]);
      if (registry.status === 401 || runs.status === 401) { window.location.assign("/login"); return; }
      if (!registry.ok || !runs.ok) throw new Error("Agent records could not be loaded.");
      setAgents(await registry.json());
      setHistory(await runs.json());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent service is unavailable."); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function execute(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(""); setError("");
    try {
      const response = await fetch("/api/agents", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ agent: selected, ...(incidentId ? { incident_id: incidentId } : {}) }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Agent execution failed.");
      setMessage(`${result.agent} completed. Review the cited records before acting.`);
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent execution failed."); }
    finally { setBusy(false); }
  }

  return <main className="agents-page">
    <header className="agents-header"><div><div className="agents-kicker">AUTOMATION / INTELLIGENCE</div><h1>Agent control center</h1><p>Run bounded analysis on records in your organization and review the saved output.</p></div><button className="agents-refresh" onClick={() => void load()} aria-label="Refresh agents"><RefreshCw size={15}/> Refresh</button></header>
    <div className="agents-notice"><CircleAlert size={17}/><span>Local analysis uses organization records. Open <Link href="/platform/nexus">Investigation Nexus</Link> to queue all seven agents and review their findings.</span></div>
    {error && <div className="agents-error" role="alert">{error}</div>}{message && <div className="agents-success" role="status">{message}</div>}
    <section className="agent-grid" aria-label="Available analysis agents">{agents.map(agent => <article className={`agent-card ${selected === agent.name ? "agent-selected" : ""}`} key={agent.name}><div className="agent-card-top"><span className="agent-icon"><Bot size={18}/></span><span className="agent-status"><i/>{agent.status.replaceAll("_", " ")}</span></div><h2>{agent.name}</h2><p>{agent.responsibility}</p><div className="agent-capability"><ShieldCheck size={14}/> Human review {agent.human_approval_required ? "required" : "recommended"}</div><button type="button" className="agent-select" onClick={() => setSelected(agent.name)} aria-pressed={selected === agent.name}>{selected === agent.name ? "Selected" : "Select agent"}</button></article>)}</section>
    <section className="agent-run panel"><div><div className="agents-kicker">TASK RUNNER</div><h2>Analyze organization records</h2><p>Reads tenant-scoped incidents, graph data, and evidence metadata. Does not change source records.</p></div><form onSubmit={execute}><label htmlFor="agent-select">Agent</label><select id="agent-select" value={selected} onChange={event => setSelected(event.target.value)}>{agents.map(agent => <option key={agent.name} value={agent.name}>{agent.name}</option>)}</select><label htmlFor="agent-incident">Optional incident ID</label><input id="agent-incident" value={incidentId} onChange={event => setIncidentId(event.target.value)} placeholder="Limit analysis to one incident"/><button className="agents-run-button" type="submit" disabled={busy || !agents.length}><Play size={15}/>{busy ? "Analyzing…" : "Run analysis"}</button></form></section>
    <section className="agent-history"><div className="agent-history-title"><div><div className="agents-kicker">PERSISTED RUNS</div><h2>Execution history</h2></div><span>{history.length} saved</span></div>{history.length ? history.map(run => <article className="execution-card" key={run.id}><div className="execution-top"><div><strong>{run.agent}</strong><span>{run.status}</span></div><time><Clock3 size={13}/>{new Date(run.created_at).toLocaleString()}</time></div><p>{run.output.finding}</p><div className="execution-foot"><span><Activity size={14}/>{run.output.evidence.length} record references</span><span>{run.output.requires_approval ? "Human review required" : "Review recommended"}</span></div><small>{run.output.limitations.join(" ")}</small></article>) : <div className="agent-empty">No analyses have been run for this organization yet.</div>}</section>
  </main>;
}
