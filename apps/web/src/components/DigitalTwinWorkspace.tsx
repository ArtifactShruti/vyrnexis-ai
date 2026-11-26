"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { request, workspace } from "@/lib/ai-workspace";

type Entity = { id: string; name: string; type: string };
type Dependency = { id: string; dependent_id: string; prerequisite_id: string; kind: string; reference: string };
type Topology = { entities: Entity[]; dependencies: Dependency[]; digest?: string; truncated?: boolean };
type Impact = { affected: (Entity & { depth: number; path: string[] })[]; direct: number; indirect: number; depth_limited: boolean };
type Simulation = { id: string; topology_digest: string; input: { title: string; assumption: string; scenario_type: string };
  result: { target_entity_id: string; baseline: Impact; alternative: Impact | null; avoided_entities: string[]; limitations: string[]; topology: Topology } };
const base = "digital-twin";
type SavedSimulation = { id: string; title: string };
const options = { outage: "Infrastructure outage", application_failure: "Application failure", device_isolation: "Device isolation",
  containment: "Incident containment", account_restriction: "Account restriction", workflow_disruption: "Workflow disruption",
  policy_change: "Transaction policy change", dependency_removal: "Dependency removal" };

export default function DigitalTwinWorkspace() {
  const [live, setLive] = useState<Topology>();
  const [saved, setSaved] = useState<SavedSimulation[]>([]);
  const [active, setActive] = useState<Simulation>();
  const [entity, setEntity] = useState("");
  const [kind, setKind] = useState("outage");
  const [filter, setFilter] = useState("");
  const [onlyImpact, setOnlyImpact] = useState(false);
  const [alternative, setAlternative] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [canEdit, setCanEdit] = useState(false);
  const [requestKey, setRequestKey] = useState<{ fingerprint: string; key: string }>();
  const topology = active?.result.topology || live;
  const impact = alternative && active?.result.alternative ? active.result.alternative : active?.result.baseline;
  const labels = new Map(topology?.entities.map(item => [item.id, item.name]));
  const types = [...new Set(topology?.entities.map(item => item.type))].sort();
  const impacted = new Set(impact?.affected.map(item => item.id));
  const visible = topology?.entities.filter(item => (!filter || item.type === filter) && (!onlyImpact || impacted.has(item.id))) || [];
  const chart = visible.slice(0, 60);
  const point = new Map(chart.map((item, index) => [item.id, { x: 80 + (index % 5) * 150, y: 42 + Math.floor(index / 5) * 75 }]));
  const selected = topology?.entities.find(item => item.id === entity);
  const selectedImpact = impact?.affected.find(item => item.id === entity);

  const load = useCallback(async () => {
    const [data, history] = await Promise.all([workspace<Topology>(`${base}/topology`),
      workspace<SavedSimulation[]>(`${base}/simulations`)]);
    setLive(data); setSaved(history);
  }, []);
  useEffect(() => {
    void Promise.all([load(), fetch("/api/auth/session").then(async response => {
      if (response.ok) setCanEdit(["owner", "organization_admin", "security_analyst", "forensic_investigator", "automation_engineer"]
        .includes((await response.json()).user.role));
    })]).catch(cause => setError(cause.message)).finally(() => setLoading(false));
  }, [load]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Digital Twin request failed."); }
    finally { setBusy(false); }
  }
  function choose(row: Simulation) {
    setActive(row); setAlternative(false); setFilter(""); setOnlyImpact(false); setEntity(row.result.target_entity_id);
  }
  const chartHeight = Math.max(310, Math.ceil(chart.length / 5) * 75);

  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Digital Twin</h1><p>Trace hypothetical impacts through recorded dependencies.</p></div>
      <Link className="agents-refresh" href="/platform/graph">Intelligence graph</Link></header>
    {error && <p className="agents-error" role="alert">{error}</p>}{message && <p className="agents-success" role="status">{message}</p>}
    <div className="intake-layout studio-layout">
      <aside className="panel intake-panel"><h2>Topology</h2>
        {loading && <p role="status">Loading topology…</p>}
        {live?.truncated && <p role="alert">The topology exceeds the simulation size limit.</p>}
        <div className="detection-form"><label>Entity type<select value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="">All types</option>{types.map(type => <option key={type}>{type}</option>)}</select></label>
          {active && <label className="ai-check"><input type="checkbox" checked={onlyImpact} onChange={event => setOnlyImpact(event.target.checked)}/> Affected entities only</label>}
          {visible.length > 0 && <label>Inspect entity<select value={entity} onChange={event => setEntity(event.target.value)}>
            <option value="">Choose entity</option>{visible.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>}
        </div>
        <h3>Saved simulations</h3>
        {!saved.length && <p>No saved simulations.</p>}
        <div className="intake-list">{saved.map(item => <button key={item.id} type="button" disabled={busy} aria-pressed={active?.id === item.id}
          onClick={() => void act(async () => choose(await workspace<Simulation>(`${base}/simulations/${item.id}`)))}>{item.title}</button>)}</div>
        {active && <button type="button" className="agents-refresh" onClick={() => { setActive(undefined); setOnlyImpact(false); setFilter(""); }}>Return to current topology</button>}
        {canEdit && !!live?.entities.length && <details className="detection-history"><summary>Record a dependency</summary>
          <form className="detection-form" onSubmit={event => {
            event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
            void act(async () => {
              await workspace(`${base}/dependencies`, request("POST", { ...Object.fromEntries(data), confidence: Number(data.get("confidence")) }));
              await load(); form.reset(); setMessage("Dependency recorded.");
            });
          }}>
            {[["dependent_id", "Dependent entity"], ["prerequisite_id", "Prerequisite entity"]].map(([field, label]) =>
              <label key={field}>{label}<select name={field} required><option value="">Select entity</option>
                {live.entities.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>)}
            <label>Dependency type<select name="kind"><option value="depends_on">Operational</option>
              <option value="data_depends_on">Data flow</option><option value="process_depends_on">Business process</option></select></label>
            <label>Analyst confidence (0–1)<input name="confidence" required type="number" step=".01" min={0} max={1}/></label>
            <label>Evidence or rationale<input name="reason" minLength={3} maxLength={500} required/></label><button className="agents-refresh" disabled={busy}>Record dependency</button>
          </form>
        </details>}
      </aside>
      <section className="panel intake-panel"><h2>{active?.input.title || "Current dependency topology"}</h2>
        <p>{visible.length} entities in view · Showing up to 60 on the canvas</p>
        {active?.result.alternative && <div className="intake-actions"><button className="agents-refresh" type="button" aria-pressed={!alternative} onClick={() => setAlternative(false)}>Base impact</button>
          <button className="agents-refresh" type="button" aria-pressed={alternative} onClick={() => setAlternative(true)}>Mitigation impact</button></div>}
        <div className="intake-actions"><button type="button" className="agents-refresh" onClick={() => setZoom(value => Math.min(1.5, value + .15))}>Zoom in</button>
          <button type="button" className="agents-refresh" onClick={() => setZoom(value => Math.max(.65, value - .15))}>Zoom out</button></div>
        {!chart.length && !loading && <p>No recorded entities match this view.</p>}
        {!!chart.length && <div className="studio-canvas"><svg width={760 * zoom} height={chartHeight * zoom} viewBox={`0 0 760 ${chartHeight}`} aria-label="Dependency topology">
          <defs><marker id="twin-pointer" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#82afd2"/></marker></defs>
          {topology?.dependencies.map(edge => {
            const from = point.get(edge.dependent_id), to = point.get(edge.prerequisite_id);
            if (!from || !to) return null;
            const angle = Math.atan2(to.y - from.y, to.x - from.x);
            return <line key={edge.id} x1={from.x} y1={from.y} x2={to.x - Math.cos(angle) * 25} y2={to.y - Math.sin(angle) * 20}
              className="twin-edge" markerEnd="url(#twin-pointer)"><title>{labels.get(edge.dependent_id)} depends on {labels.get(edge.prerequisite_id)}</title></line>;
          })}
          {chart.map(item => {
            const p = point.get(item.id)!;
            return <g className={`twin-entity ${impacted.has(item.id) ? "affected" : ""} ${entity === item.id ? "selected" : ""}`}
              key={item.id} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button" aria-label={item.name}
              onClick={() => setEntity(item.id)} onKeyDown={event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); setEntity(item.id); } }}>
              <rect x={-55} y={-16} width={110} height={36} rx={8}/><text x={0} y={5} textAnchor="middle">{item.name.length > 15 ? item.name.slice(0, 13) + "…" : item.name}</text><title>{item.name}</title>
            </g>;
          })}
        </svg></div>}
        {impact && <div className="intake-actions" aria-label="Hypothetical affected counts"><strong>{impact.direct} direct · {impact.indirect} indirect</strong>
          {impact.depth_limited && <span>Depth limit reached</span>}
          <a className="agents-refresh" href={`/api/workspace/${base}/simulations/${active?.id}/export`}>Export simulation</a></div>}
      </section>
      <aside className="panel intake-panel"><h2>Impact inspector</h2>
        {selected && <><h3>{selected.name}</h3><p>{selected.type}</p><Link className="subtle-link" href={`/platform/graph?focus=${selected.id}`}>Open intelligence entity</Link>
          {selectedImpact && <p>Propagation path · {selectedImpact.path.map(id => labels.get(id) || id).join(" → ")}</p>}</>}
        {active && <><p>Assumption · {active.input.assumption}</p><ul className="detection-sources">{active.result.limitations.map(line => <li key={line}>{line}</li>)}</ul>
          {!!active.result.avoided_entities.length && <p>Mitigation avoids {active.result.avoided_entities.length} modeled impacts.</p>}</>}
        {canEdit && !!live?.entities.length && <form className="detection-form" onSubmit={event => {
          event.preventDefault(); const data = new FormData(event.currentTarget);
          const settings = { title: data.get("title"), scenario_type: kind, target_id: data.get("target"), assumption: data.get("assumption"),
            depth: Number(data.get("depth")), excluded_dependencies: data.getAll("exclude") };
          const fingerprint = JSON.stringify(settings);
          const key = requestKey?.fingerprint === fingerprint ? requestKey.key : crypto.randomUUID();
          setRequestKey({ fingerprint, key });
          void act(async () => { choose(await workspace<Simulation>(`${base}/simulations`, request("POST", { ...settings, request_key: key })));
            setRequestKey(undefined); await load(); });
        }}>
          <h3>New simulation</h3>
          <label>Title<input name="title" maxLength={120} required/></label>
          <label>Scenario type<select value={kind} onChange={event => setKind(event.target.value)}>{Object.entries(options).map(([value, text]) =>
            <option value={value} key={value}>{text}</option>)}</select></label>
          <label>Target<select key={kind} name="target" required><option value="">Choose target</option>
            {kind === "dependency_removal" ? live.dependencies.map(row => <option key={row.id} value={row.id}>{row.reference || row.kind}</option>)
              : live.entities.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Scenario assumption<input name="assumption" minLength={3} maxLength={500} required/></label>
          <label>Propagation depth<input type="number" name="depth" required min={1} max={8} defaultValue={4}/></label>
          {!!live.dependencies.length && <label>Dependencies bypassed by mitigation<select name="exclude" multiple size={3}>
            {live.dependencies.map(row => <option key={row.id} value={row.id}>{row.reference || row.kind}</option>)}</select></label>}
          <button className="primary-button" disabled={busy || live.truncated}>{busy ? "Evaluating…" : "Simulate impact"}</button>
        </form>}
      </aside>
    </div>
  </main>;
}
