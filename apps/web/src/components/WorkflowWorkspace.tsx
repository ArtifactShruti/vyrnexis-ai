"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { request, workspace } from "@/lib/ai-workspace";

type Kind = "manual" | "schedule" | "event" | "condition" | "map" | "approval" | "incident" | "refund" | "custody" | "agent" | "summary";
type Node = { id: string; label: string; kind: Kind; x: number; y: number; fact?: string | null;
  target?: string | null; equals?: string | number | boolean | null; interval_minutes?: number | null; agent?: string | null;
  event_type?: string | null };
type Edge = { source: string; target: string; branch: "always" | "true" | "false" };
type Graph = { nodes: Node[]; edges: Edge[] };
type Flow = { id: string; name: string; state: string; revision: number; published_version: number | null; next_due: string | null };
type Detail = Flow & { graph: Graph; versions: { number: number; created_at: string }[] };
type Run = { id: string; workflow_id: string; mode: string; status: string; version: number | null; parent_id: string | null; error: string | null; created_at: string };
type Execution = Run & { graph: Graph; steps: { node_id: string; status: string; attempt: number; error: string | null; output: object | null }[];
  approvals: { node_id: string; status: string; note: string | null }[] };
const base = "workflow-studio";
const library: Record<Kind, string> = { manual: "Manual trigger", schedule: "Scheduled trigger", event: "Tenant event trigger", condition: "Condition",
  map: "Value mapping", approval: "Human approval", incident: "Read incident", refund: "Read refund finding",
  custody: "Check custody ledger", agent: "Read saved agent finding", summary: "Count recorded risks" };
const blank: Graph = { nodes: [], edges: [] };
const busyRun = ["queued", "running", "waiting_approval"];

export default function WorkflowWorkspace() {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [templates, setTemplates] = useState<{ id: string; title: string }[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail>();
  const [graph, setGraph] = useState<Graph>(blank);
  const [past, setPast] = useState<Graph[]>([]);
  const [future, setFuture] = useState<Graph[]>([]);
  const [name, setName] = useState("");
  const [activeNode, setActiveNode] = useState("");
  const [libraryFilter, setLibraryFilter] = useState("");
  const [zoom, setZoom] = useState(1);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState("");
  const [execution, setExecution] = useState<Execution>();
  const [role, setRole] = useState("");
  const [facts, setFacts] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const drag = useRef<{ id: string; x: number; y: number; clientX: number; clientY: number; previous: Graph } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const [operationKey, setOperationKey] = useState<{ action: string; key: string }>();
  const editor = ["owner", "organization_admin", "automation_engineer"].includes(role);
  const reviewer = ["owner", "organization_admin", "security_analyst", "forensic_investigator"].includes(role);
  const dirty = !!detail && (name !== detail.name || JSON.stringify(graph) !== JSON.stringify(detail.graph));
  const node = graph.nodes.find(item => item.id === activeNode);

  const refreshRuns = useCallback(async (id: string, signal?: AbortSignal) => {
    setRuns(await workspace<Run[]>(`${base}/executions?workflow_id=${encodeURIComponent(id)}`, { signal }));
  }, []);

  async function loadInventory() { setFlows(await workspace<Flow[]>(`${base}/workflows`)); }
  useEffect(() => {
    void Promise.all([loadInventory(), workspace<typeof templates>(`${base}/templates`).then(setTemplates),
      fetch("/api/auth/session").then(async response => { if (response.ok) setRole((await response.json()).user.role); })])
      .catch(cause => setError(cause.message)).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    void workspace<Detail>(`${base}/workflows/${selected}`, { signal: controller.signal }).then(value => {
      setDetail(value); setGraph(value.graph); setName(value.name); setPast([]); setFuture([]);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    void refreshRuns(selected, controller.signal).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected, refreshRuns]);
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await workspace<Execution>(`${base}/executions/${runId}`, { signal: controller.signal });
        setExecution(next);
        setRuns(current => current.map(row => row.id === next.id ? next : row));
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Execution unavailable.");
      }
    }
    void poll();
    const timer = window.setInterval(() => { if (!document.hidden) void poll(); }, 3500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [runId]);
  useEffect(() => {
    function protect(event: BeforeUnloadEvent) { if (dirty) event.preventDefault(); }
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirty]);

  async function act(work: () => Promise<void>) {
    setError(""); setMessage(""); setBusy(true);
    try { await work(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Workflow request failed."); }
    finally { setBusy(false); }
  }
  function pick(id: string) {
    if (id === selected || (dirty && !window.confirm("Discard the unsaved workflow changes?"))) return;
    setSelected(id); setDetail(undefined); setGraph(blank); setRunId(""); setExecution(undefined); setActiveNode(""); setRuns([]);
  }
  function change(next: Graph) { setPast(items => [...items.slice(-14), graph]); setFuture([]); setGraph(next); }
  function updateNode(part: Partial<Node>) {
    change({ ...graph, nodes: graph.nodes.map(item => item.id === activeNode ? { ...item, ...part } : item) });
  }
  async function edit(action: "save" | "publish" | "lifecycle", state?: string) {
    if (!detail) return;
    const path = `${base}/workflows/${detail.id}`;
    if (action === "save") await workspace(path, request("PUT", { revision: detail.revision, name, graph }));
    else await workspace(`${path}/${action}`, request("POST", { revision: detail.revision, ...(state ? { state } : {}) }));
    const updated = await workspace<Detail>(path);
    setDetail(updated); setGraph(updated.graph); setName(updated.name); await loadInventory(); setMessage("Workflow saved.");
  }
  async function run(dry: boolean) {
    if (!detail) return;
    const data: unknown = JSON.parse(facts);
    if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("Enter input facts as a JSON object.");
    const intent = JSON.stringify({ workflow: detail.id, dry, data });
    const key = operationKey?.action === intent ? operationKey.key : crypto.randomUUID();
    setOperationKey({ action: intent, key });
    const result = await workspace<Execution>(`${base}/workflows/${selected}/executions`,
      request("POST", { request_key: key, facts: data, dry_run: dry }));
    setOperationKey(undefined); setExecution(result); setRunId(result.id); await refreshRuns(selected);
  }

  const width = Math.max(670, ...graph.nodes.map(item => item.x + 180));
  const height = Math.max(360, ...graph.nodes.map(item => item.y + 98));
  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Workflow Studio</h1><p>Build versioned workflows and follow each execution and approval.</p></div></header>
    {error && <p className="agents-error" role="alert">{error}</p>}{message && <p className="agents-success" role="status">{message}</p>}
    <div className="intake-layout studio-layout">
      <aside className="panel intake-panel"><h2>Workflows</h2>
        {loading && <p role="status">Loading workflows…</p>}
        {!loading && !flows.length && <p>No workflows are available.</p>}
        <div className="intake-list">{flows.map(item => <button type="button" disabled={busy} key={item.id} aria-pressed={selected === item.id}
          onClick={() => pick(item.id)}><strong>{item.name}</strong><small>{item.state}{item.published_version ? ` · v${item.published_version}` : ""}</small></button>)}</div>
        {editor && <form className="detection-form" onSubmit={event => {
          event.preventDefault(); if (dirty && !window.confirm("Discard the unsaved workflow changes?")) return;
          const form = event.currentTarget; const data = new FormData(form);
          void act(async () => {
            const row = await workspace<Flow>(`${base}/workflows`, request("POST", { name: data.get("name"), template: data.get("template") || null }));
            form.reset(); setSelected(row.id); setDetail(undefined); setRunId(""); setExecution(undefined); setActiveNode(""); await loadInventory();
          });
        }}><label>Name<input name="name" maxLength={120} required/></label><label>Template<select name="template"><option value="">Blank workflow</option>
          {templates.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <button className="primary-button" disabled={busy}>Create workflow</button></form>}
        {editor && detail && detail.state !== "archived" && <section><h3>Node library</h3>
          <label className="detection-form">Find a node<input value={libraryFilter} onChange={event => setLibraryFilter(event.target.value)}/></label>
          <div className="intake-list">{Object.entries(library).filter(([, label]) => label.toLowerCase().includes(libraryFilter.toLowerCase()))
            .map(([kind, label]) => <button type="button" key={kind} disabled={graph.nodes.length >= 24} onClick={() => {
              const id = crypto.randomUUID(); change({ ...graph, nodes: [...graph.nodes, {
                id, kind: kind as Kind, label, x: 30 + (graph.nodes.length % 4) * 166, y: 48 + Math.floor(graph.nodes.length / 4) * 96,
                ...(kind === "schedule" ? { interval_minutes: 60 } : {}),
              }] }); setActiveNode(id);
            }}>{label}</button>)}</div>
        </section>}
      </aside>
      <section className="panel intake-panel">
        <h2>{detail?.name || "Workflow canvas"}</h2>
        {!detail && <p>Select or create a workflow.</p>}
        {detail && <>
          <div className="intake-actions">
            <button className="agents-refresh" type="button" onClick={() => setZoom(value => Math.max(.65, value - .15))}>Zoom out</button>
            <button className="agents-refresh" type="button" onClick={() => setZoom(value => Math.min(1.6, value + .15))}>Zoom in</button>
            <button className="agents-refresh" type="button" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void canvas.current?.requestFullscreen?.(); }}>Fullscreen</button>
            {editor && <>
              <button className="agents-refresh" type="button" disabled={!past.length} onClick={() => {
                setFuture([graph, ...future]); setGraph(past[past.length - 1]); setPast(past.slice(0, -1));
              }}>Undo</button>
              <button className="agents-refresh" type="button" disabled={!future.length} onClick={() => {
                setPast([...past, graph]); setGraph(future[0]); setFuture(future.slice(1));
              }}>Redo</button>
            </>}
          </div>
          <div className="studio-canvas" ref={canvas} tabIndex={0} aria-label="Workflow node canvas">
            <div style={{ width: width * zoom, height: height * zoom }}><div className="studio-stage" style={{ width, height, transform: `scale(${zoom})` }}>
              <svg width={width} height={height} aria-hidden="true" className="studio-edges">
                {graph.edges.map((edge, index) => {
                  const from = graph.nodes.find(item => item.id === edge.source); const to = graph.nodes.find(item => item.id === edge.target);
                  if (!from || !to) return null;
                  return <g key={index}><line x1={from.x + 75} y1={from.y + 26} x2={to.x + 75} y2={to.y + 26} className={`studio-${edge.branch}`}/>
                    {edge.branch !== "always" && <text x={(from.x + to.x) / 2 + 75} y={(from.y + to.y) / 2 + 19}>{edge.branch}</text>}</g>;
                })}
              </svg>
              {graph.nodes.map(item => <button key={item.id} className="studio-node" type="button" aria-pressed={activeNode === item.id} style={{ left: item.x, top: item.y }}
                onClick={() => setActiveNode(item.id)} onPointerDown={event => {
                  if (!editor || detail.state === "archived" || event.button !== 0) return;
                  drag.current = { id: item.id, x: item.x, y: item.y, clientX: event.clientX, clientY: event.clientY, previous: graph };
                  event.currentTarget.setPointerCapture(event.pointerId);
                }} onPointerMove={event => {
                  const data = drag.current; if (data?.id !== item.id) return;
                  const x = Math.max(0, Math.min(2400, Math.round((data.x + (event.clientX - data.clientX) / zoom) / 8) * 8));
                  const y = Math.max(0, Math.min(1800, Math.round((data.y + (event.clientY - data.clientY) / zoom) / 8) * 8));
                  if (x !== item.x || y !== item.y) setGraph({ ...graph, nodes: graph.nodes.map(entry => entry.id === item.id ? { ...entry, x, y } : entry) });
                }} onLostPointerCapture={() => {
                  const data = drag.current; if (data && (item.x !== data.x || item.y !== data.y)) {
                    setPast(items => [...items.slice(-14), data.previous]); setFuture([]);
                  } drag.current = null;
                }}><strong>{item.label}</strong><small>{execution?.steps.find(step => step.node_id === item.id)?.status.replaceAll("_", " ") || library[item.kind]}</small></button>)}
            </div></div>
          </div>
          {editor && detail.state !== "archived" && <div className="intake-actions">
            <button className="agents-refresh" disabled={busy} onClick={() => void act(async () => { await workspace(`${base}/validate`, request("POST", graph)); setMessage("Graph is valid."); })}>Validate</button>
            <button className="primary-button" disabled={busy || !dirty} onClick={() => void act(() => edit("save"))}>Save draft</button>
            <button className="agents-refresh" disabled={busy || dirty} onClick={() => void act(() => edit("publish"))}>Publish</button>
            {detail.state === "published" && <button className="agents-refresh" disabled={busy || dirty} onClick={() => void act(() => edit("lifecycle", "paused"))}>Pause</button>}
            {detail.state === "paused" && <button className="agents-refresh" disabled={busy || dirty} onClick={() => void act(() => edit("lifecycle", "published"))}>Resume</button>}
            <button className="agents-refresh" disabled={busy || dirty} onClick={() => {
              if (window.confirm("Archive this workflow? Its execution history will be retained.")) void act(() => edit("lifecycle", "archived"));
            }}>Archive</button>
          </div>}
          <details className="detection-history"><summary>Published versions ({detail.versions.length})</summary>
            <ol className="detection-sources">{detail.versions.map(item => <li key={item.number}>Version {item.number} · {new Date(item.created_at).toLocaleString()}</li>)}</ol></details>
        </>}
      </section>
      <aside className="panel intake-panel"><h2>Inspector</h2>
        {detail && editor && detail.state !== "archived" && <>
          <div className="detection-form"><label>Workflow name<input value={name} maxLength={120} onChange={event => setName(event.target.value)}/></label></div>
          {node && <div className="detection-form">
            <h3>{library[node.kind]}</h3><label>Label<input value={node.label} maxLength={120} onChange={event => updateNode({ label: event.target.value })}/></label>
            {["condition", "map", "incident", "refund", "custody", "agent"].includes(node.kind) && <label>Input fact name<input value={node.fact || ""}
              maxLength={48} onChange={event => updateNode({ fact: event.target.value || null })}/></label>}
            {node.kind === "condition" && <label>Equals (text)<input value={String(node.equals ?? "")} onChange={event => updateNode({ equals: event.target.value })}/></label>}
            {node.kind === "map" && <label>Output field<input value={node.target || ""} onChange={event => updateNode({ target: event.target.value || null })}/></label>}
            {node.kind === "schedule" && <label>Interval in minutes<input type="number" min={5} max={1440} value={node.interval_minutes || ""}
              onChange={event => updateNode({ interval_minutes: Number(event.target.value) || null })}/></label>}
            {node.kind === "event" && <label>Watched event<select value={node.event_type || ""} onChange={event => updateNode({ event_type: event.target.value || null })}>
              <option value="">Select event</option><option value="security_event">New security event</option>
              <option value="fraud_finding">New refund finding</option><option value="incident">New incident</option></select></label>}
            {node.kind === "agent" && <label>Agent<select value={node.agent || ""} onChange={event => updateNode({ agent: event.target.value || null })}>
              <option value="">Select agent</option>{["SENTINEL","MERCURY","TRACE","ORACLE","AEGIS","VERITAS","NEXUS"].map(agent => <option key={agent}>{agent}</option>)}</select></label>}
            <button className="agents-refresh" type="button" onClick={() => {
              change({ nodes: graph.nodes.filter(item => item.id !== node.id), edges: graph.edges.filter(edge => ![edge.source, edge.target].includes(node.id)) });
              setActiveNode("");
            }}>Remove node</button>
          </div>}
          {!!node && <form className="detection-form" key={node.id} onSubmit={event => {
            event.preventDefault(); const form = new FormData(event.currentTarget);
            const edge: Edge = { source: node.id, target: String(form.get("to")), branch: node.kind === "condition" ? form.get("branch") as Edge["branch"] : "always" };
            change({ ...graph, edges: [...graph.edges, edge] });
          }}>
            <label>Connect to<select name="to" required><option value="">Choose a node</option>{graph.nodes.filter(item => item.id !== node.id).map(item =>
              <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            {node.kind === "condition" && <label>Branch<select name="branch"><option value="true">True</option><option value="false">False</option></select></label>}
            <button className="agents-refresh" disabled={graph.edges.length >= 64}>Add connection</button>
            {graph.edges.map((edge, index) => edge.source === node.id && <button key={index} className="agents-refresh" type="button"
              onClick={() => change({ ...graph, edges: graph.edges.filter((_, position) => position !== index) })}>Remove link to {graph.nodes.find(item => item.id === edge.target)?.label}</button>)}
          </form>}
        </>}
        {detail && <><h3>Executions</h3>
          {detail.next_due && <p>Next trigger check {new Date(detail.next_due).toLocaleString()}</p>}
          {editor && detail.state !== "archived" && <div className="detection-form"><label>Input facts (JSON)<textarea rows={3} value={facts} onChange={event => setFacts(event.target.value)}/></label>
            <div className="intake-actions"><button className="agents-refresh" disabled={busy || dirty} onClick={() => void act(() => run(true))}>Run draft</button>
              <button className="agents-refresh" disabled={busy || detail.state !== "published"} onClick={() => void act(() => run(false))}>Run published</button></div></div>}
          <div className="intake-list">{runs.map(item => <button key={item.id} type="button" aria-pressed={item.id === runId} onClick={() => { setRunId(item.id); setExecution(undefined); }}>
            <strong>{item.mode.replaceAll("_", " ")} · {item.status.replaceAll("_", " ")}</strong><small>{new Date(item.created_at).toLocaleString()}</small></button>)}</div>
          {execution && <section aria-label="Execution timeline"><h3>{execution.status.replaceAll("_", " ")}</h3>
            {execution.error && <p role="alert">{execution.error}</p>}
            <ol className="detection-sources">{execution.steps.map(step => <li key={step.node_id}>
              <strong>{execution.graph.nodes.find(item => item.id === step.node_id)?.label}</strong><small>{step.status.replaceAll("_", " ")} · attempt {step.attempt}</small>
              {step.output && <pre className="ai-wrap">{JSON.stringify(step.output, null, 2)}</pre>}{step.error && <p>{step.error}</p>}
            </li>)}</ol>
            {reviewer && execution.approvals.filter(item => item.status === "pending").map(item => <form className="detection-form" key={item.node_id}
              onSubmit={event => {
                event.preventDefault(); const data = new FormData(event.currentTarget);
                void act(async () => setExecution(await workspace<Execution>(`${base}/executions/${execution.id}/approvals/${item.node_id}`,
                  request("POST", { decision: data.get("decision"), note: data.get("note") }))));
              }}><label>Decision<select name="decision"><option value="approved">Approve</option><option value="rejected">Reject</option></select></label>
              <label>Review note<input required minLength={3} maxLength={500} name="note"/></label><button className="primary-button" disabled={busy}>Record decision</button></form>)}
            {editor && busyRun.includes(execution.status) && <button className="agents-refresh" disabled={busy}
              onClick={() => void act(async () => setExecution(await workspace<Execution>(`${base}/executions/${execution.id}/cancel`, request("POST"))))}>Cancel run</button>}
            {editor && ["failed", "cancelled", "timed_out"].includes(execution.status) && <button className="agents-refresh" disabled={busy}
              onClick={() => void act(async () => {
                const intent = `replay-${execution.id}`; const key = operationKey?.action === intent ? operationKey.key : crypto.randomUUID();
                setOperationKey({ action: intent, key });
                const next = await workspace<Execution>(`${base}/executions/${execution.id}/replay`, request("POST", { request_key: key }));
                setOperationKey(undefined); setExecution(next); setRunId(next.id); await refreshRuns(selected);
              })}>Replay execution</button>}
          </section>}
        </>}
      </aside>
    </div>
  </main>;
}
