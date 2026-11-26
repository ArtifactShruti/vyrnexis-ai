"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, ArrowUpRight, Bookmark, Download, Expand,
  Focus, Fullscreen, LoaderCircle, Minus, Network, Plus, Search, Shield,
  SlidersHorizontal, X,
} from "lucide-react";

type Entity = {
  id: string; entity_type: string; external_id: string; display_name: string;
  properties: Record<string, unknown>; created_at: string;
};
type Relationship = {
  id: string; source_id: string; target_id: string; source: string; target: string;
  relationship_type: string; confidence: number; source_reference: string; occurred_at: string;
};
type TimelineEvent = {
  id: string; event_type: "relationship" | "incident" | "evidence"; timestamp: string;
  label: string; reference: string; entity_id: string | null;
};
type GraphData = {
  organization_id: string; focus_id: string | null; truncated: boolean;
  entities: Entity[]; relationships: Relationship[]; timeline: TimelineEvent[];
};
type BookmarkRecord = { id: string; name: string; entity_ids: string[]; filters: Record<string, string> };
type Principal = { user: { id: string; name: string; role: string }; organization: { id: string; name: string } };

const typeColors: Record<string, string> = {
  user: "#60a5fa", device: "#22d3ee", ip_address: "#34d399", security_event: "#f59e0b",
  transaction: "#a78bfa", refund: "#a78bfa", account: "#60a5fa", evidence: "#f472b6", asset: "#fb923c", incident: "#fb7185",
};
const formatDate = (value: string) => new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

function shortestPath(edges: Relationship[], start: string, end: string) {
  if (!start || !end || start === end) return null;
  const neighbors = new Map<string, { node: string; edge: string }[]>();
  for (const edge of edges) {
    neighbors.set(edge.source_id, [...(neighbors.get(edge.source_id) || []), { node: edge.target_id, edge: edge.id }]);
    neighbors.set(edge.target_id, [...(neighbors.get(edge.target_id) || []), { node: edge.source_id, edge: edge.id }]);
  }
  const pending = [start];
  const predecessors = new Map<string, { node: string; edge: string }>([[start, { node: "", edge: "" }]]);
  for (let i = 0; i < pending.length && !predecessors.has(end); i++) {
    const node = pending[i];
    for (const next of neighbors.get(node) || []) {
      if (predecessors.has(next.node)) continue;
      predecessors.set(next.node, { node, edge: next.edge });
      pending.push(next.node);
    }
  }
  if (!predecessors.has(end)) return null;
  const nodes = [end];
  const edgeIds = new Set<string>();
  let cursor = end;
  while (cursor !== start) {
    const step = predecessors.get(cursor)!;
    edgeIds.add(step.edge);
    cursor = step.node;
    nodes.unshift(cursor);
  }
  return { nodes, edgeIds };
}

export default function IntelligenceGraphPage() {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [bookmarks, setBookmarks] = useState<BookmarkRecord[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState("");
  const [selectedRelationshipId, setSelectedRelationshipId] = useState("");
  const [selectedTimeline, setSelectedTimeline] = useState<TimelineEvent | null>(null);
  const [search, setSearch] = useState("");
  const [relationFilter, setRelationFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [pathStart, setPathStart] = useState("");
  const [pathEnd, setPathEnd] = useState("");
  const [layout, setLayout] = useState<"orbit" | "type">("orbit");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [bookmarkName, setBookmarkName] = useState("");
  const [bookmarkMessage, setBookmarkMessage] = useState("");
  const [showMinimap, setShowMinimap] = useState(true);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  const loadGraph = useCallback(async (focusId?: string) => {
    setLoading(true);
    setError("");
    try {
      const query = focusId ? `?focus_id=${encodeURIComponent(focusId)}` : "";
      const response = await fetch(`/api/intelligence/graph${query}`, { cache: "no-store" });
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Graph data could not be loaded.");
      setGraph(body);
      setSelectedRelationshipId("");
      setSelectedTimeline(null);
      setSelectedEntityId(focusId || body.entities[0]?.id || "");
      setPan({ x: 0, y: 0 });
      setZoom(1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Graph service is unavailable.");
    } finally { setLoading(false); }
  }, []);

  const loadBookmarks = useCallback(async () => {
    const response = await fetch("/api/intelligence/bookmarks", { cache: "no-store" });
    if (response.status === 401) return;
    if (response.ok) setBookmarks(await response.json());
  }, []);

  useEffect(() => {
    let active = true;
    const initialize = async () => {
      try {
        let session = await fetch("/api/auth/session", { cache: "no-store" });
        if (session.status === 401) session = await fetch("/api/auth/refresh", { method: "POST", cache: "no-store" });
        if (session.status === 401) { window.location.assign("/login"); return; }
        if (!session.ok) throw new Error("Session could not be verified.");
        const identity = await session.json();
        if (!active) return;
        setPrincipal(identity);
        const focus = new URLSearchParams(window.location.search).get("focus") || undefined;
        await Promise.all([loadGraph(focus), loadBookmarks()]);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Authentication service is unavailable.");
      }
    };
    void initialize();
    return () => { active = false; };
  }, [loadGraph, loadBookmarks]);

  const view = useMemo(() => {
    const containsDate = (value: string) => {
      const utcDay = value.slice(0, 10);
      return (!since || utcDay >= since) && (!until || utcDay <= until);
    };
    const matching = new Set((graph?.entities || [])
      .filter(entity => typeFilter === "all" || entity.entity_type === typeFilter)
      .map(entity => entity.id));
    const visibleLinks = (graph?.relationships || []).filter(edge =>
      (matching.has(edge.source_id) || matching.has(edge.target_id))
      && (relationFilter === "all" || edge.relationship_type === relationFilter) && containsDate(edge.occurred_at));
    const connected = new Set(visibleLinks.flatMap(edge => [edge.source_id, edge.target_id]));
    const visibleEntities = (graph?.entities || []).filter(entity => connected.has(entity.id)
      || ((!since && !until) && matching.has(entity.id)));
    const references = new Set(visibleLinks.map(edge => edge.id));
    const timeline = (graph?.timeline || []).filter(event => containsDate(event.timestamp)
      && (event.event_type !== "relationship" || references.has(event.id.replace(/^relationship:/, ""))));
    return { visibleEntities, relationships: visibleLinks, timeline };
  }, [graph, relationFilter, typeFilter, since, until]);
  const { visibleEntities, relationships, timeline } = view;
  const path = useMemo(() => shortestPath(relationships, pathStart, pathEnd), [relationships, pathStart, pathEnd]);

  const entityPositions = useMemo(() => {
    const entities = visibleEntities;
    const output: Record<string, { x: number; y: number }> = {};
    if (layout === "type") {
      const groups = new Map<string, Entity[]>();
      entities.forEach((entity) => groups.set(entity.entity_type, [...(groups.get(entity.entity_type) || []), entity]));
      const groupList = [...groups.values()];
      groupList.forEach((group, groupIndex) => {
        const x = groupList.length === 1 ? 500 : 160 + groupIndex * (680 / Math.max(1, groupList.length - 1));
        group.forEach((entity, index) => { output[entity.id] = { x, y: 145 + index * 118 }; });
      });
    } else {
      const count = Math.max(entities.length, 1);
      entities.forEach((entity, index) => {
        const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
        output[entity.id] = { x: 500 + Math.cos(angle) * Math.min(305, count * 42), y: 300 + Math.sin(angle) * Math.min(205, count * 29) };
      });
    }
    return output;
  }, [visibleEntities, layout]);

  const selectedEntity = graph?.entities.find((entity) => entity.id === selectedEntityId);
  const selectedRelationship = graph?.relationships.find((relationship) => relationship.id === selectedRelationshipId);
  const relationTypes = [...new Set((graph?.relationships || []).map((relationship) => relationship.relationship_type))];
  const entityTypes = [...new Set((graph?.entities || []).map(entity => entity.entity_type))];
  const normalizedSearch = search.trim().toLowerCase();
  const isMatch = (entity: Entity) => !normalizedSearch || `${entity.display_name} ${entity.entity_type} ${entity.external_id}`.toLowerCase().includes(normalizedSearch);

  const panStart = (event: React.PointerEvent<SVGSVGElement>) => {
    const target = event.target as SVGElement;
    if (target === event.currentTarget || target.classList.contains("graph-background")) {
      dragRef.current = { x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };
  const panMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    setPan((current) => ({
      x: current.x + (event.movementX * 1000 / rect.width) / zoom,
      y: current.y + (event.movementY * 600 / rect.height) / zoom,
    }));
  };
  const panEnd = () => { dragRef.current = null; };

  const saveBookmark = async () => {
    const name = bookmarkName.trim();
    if (!name || !graph) return;
    setWorking(true);
    setBookmarkMessage("");
    try {
      const ids = selectedEntityId ? [selectedEntityId] : graph.entities.map((entity) => entity.id);
      const response = await fetch("/api/intelligence/bookmarks", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, entity_ids: ids, filters: { relationship_type: relationFilter, layout, entity_type: typeFilter, since, until } }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Bookmark could not be saved.");
      setBookmarkName("");
      setBookmarkMessage("Bookmark saved");
      await loadBookmarks();
    } catch (cause) {
      setBookmarkMessage(cause instanceof Error ? cause.message : "Bookmark could not be saved.");
    } finally { setWorking(false); }
  };

  const exportGraph = () => {
    if (!graph) return;
    const blob = new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "vyrnexis-intelligence-graph.json";
    link.click();
    URL.revokeObjectURL(url);
  };

  const fullscreen = async () => {
    if (!canvasRef.current) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await canvasRef.current.requestFullscreen();
  };

  const openBookmark = (bookmark: BookmarkRecord) => {
    setRelationFilter(bookmark.filters.relationship_type || "all");
    setTypeFilter(bookmark.filters.entity_type || "all");
    setSince(bookmark.filters.since || "");
    setUntil(bookmark.filters.until || "");
    setLayout(bookmark.filters.layout === "type" ? "type" : "orbit");
    if (bookmark.entity_ids.length) void loadGraph(bookmark.entity_ids[0]);
  };

  return <main className="investigation-page">
    <header className="investigation-topbar"><Link href="/" className="investigation-brand"><span className="mini-brand">V</span><strong>VYRNEXIS</strong></Link><span className="investigation-divider"/><Link className="back-command" href="/"><ArrowLeft size={14}/> Command center</Link><span className="investigation-breadcrumb">/ <strong>Intelligence graph</strong></span><div className="investigation-org"><span className="live-dot"/>{principal?.organization.name || "Organization"}</div><span className="user-chip">{principal?.user.name.split(/\s+/).map((item)=>item[0]).slice(0,2).join("").toUpperCase() || "VA"}</span></header>
    <section className="investigation-heading"><div><div className="panel-kicker">VNIF / INVESTIGATION WORKSPACE</div><h1>Intelligence graph</h1><p>Explore tenant-scoped entities, supporting relationships, and recorded investigation events.</p></div><div className="graph-heading-tools"><button className="graph-button" onClick={exportGraph} disabled={!graph}><Download size={14}/> Export JSON</button><button className="graph-button" onClick={() => void loadGraph()}><Focus size={14}/> Show full graph</button></div></section>
    {error && <div className="graph-notice" role="alert"><Shield size={15}/><span>{error}</span><button onClick={() => void loadGraph()}><ArrowUpRight size={13}/> Retry</button></div>}

    <section className="investigation-layout">
      <aside className="graph-left-panel">
        <div className="graph-panel-label"><SlidersHorizontal size={13}/> EXPLORE</div>
        <label className="graph-search"><Search size={14}/><input aria-label="Search entities" placeholder="Search entities" value={search} onChange={(event)=>setSearch(event.target.value)}/><kbd>/</kbd></label>
        <label className="graph-select-label">RELATIONSHIP TYPE<select value={relationFilter} onChange={(event)=>setRelationFilter(event.target.value)}><option value="all">All recorded links</option>{relationTypes.map((type)=><option value={type} key={type}>{type.replaceAll("_", " ")}</option>)}</select></label>
        <label className="graph-select-label">ENTITY TYPE AND NEIGHBORS<select value={typeFilter} onChange={event => setTypeFilter(event.target.value)}><option value="all">All entities</option>{entityTypes.map(type => <option value={type} key={type}>{type.replaceAll("_", " ")}</option>)}</select></label>
        <label className="graph-select-label">FROM DATE (UTC)<input type="date" value={since} max={until || undefined} onChange={event => setSince(event.target.value)}/></label>
        <label className="graph-select-label">THROUGH DATE (UTC)<input type="date" value={until} min={since || undefined} onChange={event => setUntil(event.target.value)}/></label>
        <details className="detection-history graph-path"><summary>Find a connecting path</summary>
          <label className="graph-select-label">Start entity<select value={pathStart} onChange={event => setPathStart(event.target.value)}><option value="">Choose start</option>{visibleEntities.map(entity => <option key={entity.id} value={entity.id}>{entity.display_name}</option>)}</select></label>
          <label className="graph-select-label">End entity<select value={pathEnd} onChange={event => setPathEnd(event.target.value)}><option value="">Choose end</option>{visibleEntities.map(entity => <option key={entity.id} value={entity.id}>{entity.display_name}</option>)}</select></label>
          {pathStart && pathEnd && pathStart !== pathEnd && <p role="status">{path ? path.nodes.map(id => visibleEntities.find(entity => entity.id === id)?.display_name).join(" → ") : "No connection in the current graph view."}</p>}
        </details>
        <label className="graph-select-label">LAYOUT<select value={layout} onChange={(event)=>setLayout(event.target.value as "orbit" | "type")}><option value="orbit">Orbit</option><option value="type">Group by entity type</option></select></label>
        <div className="graph-counts"><div><strong>{graph ? visibleEntities.length : " - "}</strong><span>ENTITIES</span></div><div><strong>{graph ? relationships.length : " - "}</strong><span>LINKS</span></div></div>
        {graph?.truncated && <div className="graph-truncated">Graph view is limited to a recent subset. Focus an entity to explore its connections.</div>}
        <div className="bookmark-title"><Bookmark size={13}/> SAVED VIEWS</div>
        <div className="bookmark-list">{bookmarks.length ? bookmarks.map((bookmark)=><button key={bookmark.id} className="bookmark-row" onClick={()=>openBookmark(bookmark)}><span>{bookmark.name}</span><small>{bookmark.entity_ids.length} entities</small></button>) : <p>No saved graph views yet.</p>}</div>
        <div className="save-bookmark"><input aria-label="Bookmark name" value={bookmarkName} onChange={(event)=>setBookmarkName(event.target.value)} placeholder="Name this view" maxLength={160}/><button onClick={() => void saveBookmark()} disabled={working || !bookmarkName.trim()} aria-label="Save graph bookmark"><Bookmark size={14}/></button></div>
        {bookmarkMessage && <div className="bookmark-message" role="status">{bookmarkMessage}</div>}
      </aside>

      <div className="graph-main-column">
        <div className="graph-canvas-shell" ref={canvasRef}>
          <div className="graph-canvas-toolbar"><div><span className="canvas-live"><i/> STORED DATA</span><span className="canvas-caption">{graph?.focus_id ? "One-hop neighborhood" : "Organization graph"}</span></div><div className="canvas-tools"><button onClick={()=>setZoom((value)=>Math.max(.55,value-.15))} aria-label="Zoom out"><Minus size={14}/></button><span>{Math.round(zoom*100)}%</span><button onClick={()=>setZoom((value)=>Math.min(2.3,value+.15))} aria-label="Zoom in"><Plus size={14}/></button><button onClick={()=>{setZoom(1);setPan({x:0,y:0});}} aria-label="Reset zoom and position"><Expand size={13}/></button><button onClick={()=>setShowMinimap((value)=>!value)} aria-label="Toggle minimap"><Network size={14}/></button><button onClick={()=>void fullscreen()} aria-label="Toggle fullscreen"><Fullscreen size={14}/></button></div></div>
          {loading ? <div className="graph-loading"><LoaderCircle size={20} className="spin"/>Loading authorized graph records...</div> : !visibleEntities.length ? <div className="graph-empty"><div><Network size={24}/></div><strong>No entities match this view</strong><span>Change the filters or expand the organization graph.</span><Link href="/">Return to command center <ArrowUpRight size={13}/></Link></div> : <>
            <div className="graph-canvas" aria-label="Interactive intelligence graph">
              <svg viewBox="0 0 1000 600" role="img" aria-label={`${visibleEntities.length} entities and ${relationships.length} visible relationships. Use mouse or touch to pan; zoom controls are above.`} onPointerDown={panStart} onPointerMove={panMove} onPointerUp={panEnd} onPointerCancel={panEnd}>
                <rect className="graph-background" x="0" y="0" width="1000" height="600"/>
                <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
                  {relationships.map((relation)=>{
                    const source=entityPositions[relation.source_id]; const target=entityPositions[relation.target_id];
                    if(!source||!target)return null;
                    const selected=selectedRelationshipId===relation.id;
                    return <g key={relation.id} className={`graph-edge ${selected?"edge-selected":""} ${path?.edgeIds.has(relation.id)?"edge-path":""}`} tabIndex={0} role="button" aria-label={`${relation.source} ${relation.relationship_type} ${relation.target}`} onClick={()=>{setSelectedRelationshipId(relation.id);setSelectedEntityId("");setSelectedTimeline(null);}} onKeyDown={(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();setSelectedRelationshipId(relation.id);setSelectedEntityId("");setSelectedTimeline(null);}}}><line x1={source.x} y1={source.y} x2={target.x} y2={target.y}/><title>{`${relation.source} ${relation.relationship_type} ${relation.target} | ${relation.confidence} confidence | ${relation.source_reference}`}</title></g>;
                  })}
                  {visibleEntities.map((entity)=>{
                    const point=entityPositions[entity.id]; if(!point)return null;
                    const matched=isMatch(entity); const color=typeColors[entity.entity_type]||"#94a3b8";
                    return <g key={entity.id} className={`graph-node ${selectedEntityId===entity.id?"node-selected":""} ${matched?"":"node-dimmed"}`} transform={`translate(${point.x} ${point.y})`} role="button" tabIndex={0} aria-label={`${entity.entity_type}: ${entity.display_name}`} onClick={()=>{setSelectedEntityId(entity.id);setSelectedRelationshipId("");setSelectedTimeline(null);}} onKeyDown={(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();setSelectedEntityId(entity.id);setSelectedRelationshipId("");setSelectedTimeline(null);}}}>
                      <circle r="29" style={{stroke:color}}/><circle className="node-core" r="20" style={{fill:`${color}1a`,stroke:color}}/><text className="node-type" y="-2">{entity.entity_type.replaceAll("_", " ").slice(0,15).toUpperCase()}</text><text className="node-name" y="48">{entity.display_name.length>22?`${entity.display_name.slice(0,21)}...`:entity.display_name}</text>
                    </g>;
                  })}
                </g>
              </svg>
              {showMinimap && <div className="graph-minimap"><span>OVERVIEW</span><svg viewBox="0 0 1000 600" aria-label="Graph minimap">{relationships.map((relation)=>{const a=entityPositions[relation.source_id],b=entityPositions[relation.target_id];return a&&b?<line key={relation.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y}/>:null;})}{visibleEntities.map((entity)=>{const p=entityPositions[entity.id];return p?<circle key={entity.id} cx={p.x} cy={p.y} r="16"/>:null;})}</svg></div>}
              <div className="graph-legend"><span><i style={{background:typeColors.user}}/>Identity</span><span><i style={{background:typeColors.device}}/>Device</span><span><i style={{background:typeColors.security_event}}/>Security event</span><span><i style={{background:typeColors.transaction}}/>Transaction</span><small>Confidence is an evidence attribute, not a probability.</small></div>
            </div>
          </>}
        </div>

        <section className="timeline-panel"><div className="timeline-heading"><div><div className="panel-kicker">INVESTIGATION SEQUENCE</div><h2>Recorded timeline</h2></div><span>{timeline.length} events</span></div><div className="timeline-list">{timeline.length ? timeline.slice(0,24).map((event)=><button className={`timeline-event event-${event.event_type}`} key={event.id} onClick={()=>{setSelectedTimeline(event);setSelectedEntityId("");setSelectedRelationshipId("");}}><span className="timeline-marker"/><span className="timeline-event-main"><strong>{event.label}</strong><small>{event.event_type} | {event.reference}</small></span><time>{formatDate(event.timestamp)}</time></button>) : <div className="timeline-empty">No recorded events are available for this graph.</div>}</div></section>
      </div>

      <aside className="graph-inspector">
        <div className="inspector-heading"><div><div className="panel-kicker">CONTEXTUAL INSPECTOR</div><h2>{selectedTimeline ? "Timeline event" : selectedRelationship ? "Relationship details" : "Entity details"}</h2></div><button onClick={()=>{setSelectedEntityId("");setSelectedRelationshipId("");setSelectedTimeline(null);}} aria-label="Clear selection"><X size={14}/></button></div>
        {selectedTimeline ? <div className="inspector-content"><span className="inspector-type">{selectedTimeline.event_type} record</span><h3>{selectedTimeline.label}</h3><div className="inspector-facts"><div><span>Recorded at</span><strong>{formatDate(selectedTimeline.timestamp)}</strong></div><div><span>Reference</span><strong className="inspector-mono">{selectedTimeline.reference||"Not provided"}</strong></div><div><span>Record type</span><strong>{selectedTimeline.event_type}</strong></div></div><p className="inspector-note">Timeline entries reflect stored organization records. They do not establish causation.</p></div> : selectedRelationship ? <div className="inspector-content"><span className="inspector-type">{selectedRelationship.relationship_type.replaceAll("_", " ")}</span><h3>{selectedRelationship.source}</h3><div className="relationship-direction"><span/>{selectedRelationship.relationship_type.replaceAll("_", " ")}<span/></div><h3>{selectedRelationship.target}</h3><div className="inspector-facts"><div><span>Confidence attribute</span><strong>{selectedRelationship.confidence.toFixed(2)}</strong></div><div><span>Source reference</span><strong className="inspector-mono">{selectedRelationship.source_reference||"Not provided"}</strong></div><div><span>Observed</span><strong>{formatDate(selectedRelationship.occurred_at)}</strong></div></div><p className="inspector-note">This stored relationship supports correlation. It does not independently verify causation.</p><button className="inspector-action" onClick={()=>{setSelectedEntityId(selectedRelationship.source_id);setSelectedRelationshipId("");}}>Inspect source entity <ArrowUpRight size={13}/></button></div> : selectedEntity ? <div className="inspector-content"><div className="entity-identity"><span className="inspector-entity-icon" style={{color:typeColors[selectedEntity.entity_type]||"#94a3b8"}}><Network size={19}/></span><div><span className="inspector-type">{selectedEntity.entity_type.replaceAll("_", " ")}</span><h3>{selectedEntity.display_name}</h3></div></div><div className="inspector-facts"><div><span>Entity ID</span><strong className="inspector-mono">{selectedEntity.id}</strong></div><div><span>External ID</span><strong className="inspector-mono">{selectedEntity.external_id}</strong></div><div><span>First recorded</span><strong>{formatDate(selectedEntity.created_at)}</strong></div><div><span>Connected entities</span><strong>{graph?.relationships.filter((item)=>item.source_id===selectedEntity.id||item.target_id===selectedEntity.id).length ?? 0}</strong></div></div><div className="inspector-property-title">RECORDED PROPERTIES</div><pre className="property-json">{JSON.stringify(selectedEntity.properties,null,2)}</pre>{selectedEntity.entity_type === "incident" && <Link className="inspector-action" href={`/platform/incidents?id=${encodeURIComponent(selectedEntity.external_id)}`}>Open incident <ArrowUpRight size={13}/></Link>}{selectedEntity.entity_type === "evidence" && <Link className="inspector-action" href="/platform/evidence-vault">Open Evidence Vault <ArrowUpRight size={13}/></Link>}<button className="inspector-action" onClick={()=>void loadGraph(selectedEntity.id)}><Expand size={13}/> Expand connected entities</button><button className="inspector-secondary" onClick={()=>setSearch(selectedEntity.display_name)}>Find in graph <Search size={13}/></button></div> : <div className="inspector-empty"><Network size={20}/><span>Select a node, relationship, or timeline event to inspect its stored details and provenance.</span></div>}
      </aside>
    </section>
    <footer className="graph-footer"><span>VYRNEXIS VNIF | Tenant-scoped persisted records</span><span>{graph?.truncated?"Result limit reached | use entity expansion":"Source references and timestamps shown as stored"}</span></footer>
  </main>;
}
