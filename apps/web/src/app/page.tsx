"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import DashboardActivity, { type ActivityDay } from "@/components/DashboardActivity";
import {
  Activity, AlertTriangle, ArrowUpRight, Bell, Bot, Boxes,
  ChevronDown, CircleHelp, Command, FileSearch, Fingerprint, LayoutDashboard,
  LogOut, Menu, Network, Plus, RefreshCw, Search, Settings2, Shield, ShieldCheck,
  ShoppingCart, Workflow, X
} from "lucide-react";

type Incident = { id: string; title: string; severity: string; status: string; created_at?: string };
type Entity = { id: string; entity_type: string; display_name: string };
type Relationship = { id: string; source_id: string; target_id: string; source: string; target: string; relationship_type: string; confidence: number };
type Principal = { user: { id: string; name: string; email: string; role: string }; organization: { id: string; name: string } };
type DashboardData = {
  organization: { id: string; name: string };
  active_incidents: number;
  activity?: ActivityDay[];
  database?: string;
  intelligence_entities: number;
  intelligence_relationships: number;
  recent_incidents: Incident[];
  recent_entities: Entity[];
  recent_relationships: Relationship[];
  cybersecurity_posture: number | null;
  health_score: number | null;
  investigations: { open_cases: number; assigned_cases: number; active_tasks: number; completed_tasks: number; failed_tasks: number; pending_reviews: number } | null;
};

const navigation = [
  { group: "COMMAND", items: [["Overview", LayoutDashboard, "/"], ["Live activity", Activity, "/platform/security"]] },
  { group: "SECURITY", items: [["Security operations", ShieldCheck, "/platform/security"], ["Incidents", AlertTriangle, "/platform/incidents"], ["Asset inventory", Boxes, "/platform/assets"], ["Threat intelligence", Fingerprint, "/platform/threats"]] },
  { group: "INVESTIGATION", items: [["Forensic cases", FileSearch, "/platform/forensics"], ["Investigation Nexus", Bot, "/platform/nexus"], ["Evidence vault", Fingerprint, "/platform/evidence-vault"], ["Intelligence graph", Network, "/platform/graph"], ["Digital Twin", Network, "/platform/digital-twin"]] },
  { group: "INTELLIGENCE", items: [["Copilot", Bot, "/platform/copilot"], ["Knowledge base", FileSearch, "/platform/knowledge"], ["AI settings", Settings2, "/platform/ai-settings"]] },
  { group: "BUSINESS", items: [["Fraud intelligence", Activity, "/platform/fraud"], ["E-commerce analytics", ShoppingCart, "/platform/ecommerce"], ["Business Intelligence", Activity, "/platform/analytics"], ["Data sources", Boxes, "/platform/data-sources"]] },
  { group: "AUTOMATION", items: [["AI agents", Bot, "/platform/agents"], ["Workflow studio", Workflow, "/platform/workflows"], ["Reports center", FileSearch, "/platform/reports"]] },
  { group: "ADMINISTRATION", items: [["Notifications", Bell, "/platform/notifications"], ["Users", Boxes, "/platform/users"], ["Developer API", Settings2, "/platform/developer"], ["Billing", Settings2, "/platform/billing"], ["Super administrator", Shield, "/platform/super-admin"], ["System health", Boxes, "/platform/system-health"], ["Help center", CircleHelp, "/platform/help"], ["Settings", Settings2, "/platform/settings"]] }
] as const;

function formatTime(value?: string) {
  if (!value) return " - ";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function Page() {
  const pathname = usePathname();
  const [data, setData] = useState<DashboardData | null>(null);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [commandSearch, setCommandSearch] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [sideSearch, setSideSearch] = useState("");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [profileOpen, setProfileOpen] = useState(false);
  const [unreadNotifications, setUnreadNotifications] = useState(0);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      let response = await fetch("/api/dashboard", { cache: "no-store" });
      if (response.status === 401) {
        const refreshed = await fetch("/api/auth/refresh", { method: "POST", cache: "no-store" });
        if (refreshed.status === 401) {
          window.location.assign("/login");
          return;
        }
        if (!refreshed.ok) throw new Error("Session refresh is unavailable.");
        response = await fetch("/api/dashboard", { cache: "no-store" });
      }
      if (response.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Dashboard data is unavailable. Configure the API and organization.");
      }
      const payload = await response.json();
      setData(payload);
      setEntities(payload.recent_entities || []);
      setUpdated(new Date());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Dashboard data is unavailable.");
    } finally { setBusy(false); }
  }, []);

  useEffect(() => {
    const saved = window.localStorage.getItem("vyrnexis-theme");
    const initial = saved === "light" ? "light" : "dark";
    setTheme(initial);
    document.documentElement.dataset.theme = initial;
  }, []);

  const changeTheme = (next: "dark" | "light") => {
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("vyrnexis-theme", next);
  };

  useEffect(() => {
    let active = true;
    fetch("/api/workspace/notifications/unread-count", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return;
        const result = await response.json();
        if (active) setUnreadNotifications(Number(result.count || 0));
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [data]);

  useEffect(() => {
    let active = true;
    const initialize = async () => {
      try {
        let session = await fetch("/api/auth/session", { cache: "no-store" });
        if (session.status === 401) {
          session = await fetch("/api/auth/refresh", { method: "POST", cache: "no-store" });
          if (session.status === 401) session = await fetch("/api/auth/session", { cache: "no-store" });
        }
        if (session.status === 401) {
          window.location.assign("/login");
          return;
        }
        if (!session.ok) throw new Error("Session could not be verified.");
        const identity = await session.json() as Principal;
        if (!active) return;
        setPrincipal(identity);
        await load();
      } catch {
        if (active) setError("Authentication service is unavailable.");
      }
    };
    void initialize();
    return () => { active = false; };
  }, [load]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        setCommandSearch("");
      } else if (event.key === "Escape") {
        setPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const incidents = useMemo(() => (data?.recent_incidents || []).filter((incident) => {
    const matchesText = `${incident.title} ${incident.id} ${incident.status}`.toLowerCase().includes(search.toLowerCase());
    return matchesText && (filter === "all" || incident.severity.toLowerCase() === filter);
  }), [data, search, filter]);

  const allowedGroups: Record<string, string[]> = {
    security_analyst: ["COMMAND", "SECURITY", "INVESTIGATION", "BUSINESS"],
    forensic_investigator: ["COMMAND", "SECURITY", "INVESTIGATION"],
    business_analyst: ["COMMAND", "BUSINESS"],
    automation_engineer: ["COMMAND", "AUTOMATION"],
    viewer: ["COMMAND", "SECURITY", "INVESTIGATION"],
  };
  const privileged = principal?.user.role === "owner" || principal?.user.role === "organization_admin";
  const visibleNavigation = navigation
    .filter((group) => privileged || group.group === "INTELLIGENCE" || allowedGroups[principal?.user.role || "viewer"]?.includes(group.group))
    .map((group) => ({ ...group, items: group.items.filter(([label]) => privileged || (
      label !== "Settings" && label !== "System health" && label !== "AI settings" &&
      (!["Forensic cases", "Investigation Nexus"].includes(label) || ["security_analyst", "forensic_investigator"].includes(principal?.user.role || ""))
    )) }));
  const filteredNavigation = sideSearch.trim()
    ? visibleNavigation.map((section) => ({
        ...section,
        items: section.items.filter(([label]) => label.toLowerCase().includes(sideSearch.trim().toLowerCase())),
      })).filter((section) => section.items.length)
    : visibleNavigation;
  const initials = principal?.user.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase() || "VA";
  const signOut = async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.assign("/login");
  };
  const commandItems = [
    ...visibleNavigation.flatMap((section) => section.items.map(([label, Icon, href]) => ({
      title: label, detail: section.group.toLowerCase(), href, icon: Icon,
    }))),
    ...(data?.recent_incidents || []).map((incident) => ({
      title: incident.title, detail: `Incident | ${incident.severity} | ${incident.status}`,
      href: `/platform/incidents?id=${encodeURIComponent(incident.id)}`, icon: AlertTriangle,
    })),
  ].filter((item) => `${item.title} ${item.detail}`.toLowerCase().includes(commandSearch.toLowerCase()));

  const metricItems = [
    { label: "Active incidents", value: data?.active_incidents, note: "Open investigations", icon: AlertTriangle, tone: "critical" },
    { label: "Intelligence entities", value: data?.intelligence_entities, note: "Observed in this organization", icon: Boxes, tone: "cyan" },
    { label: "Correlations", value: data?.intelligence_relationships, note: "Recorded relationships", icon: Network, tone: "violet" },
    { label: "Security posture", value: data?.cybersecurity_posture == null ? "Not measured" : `${data.cybersecurity_posture}/100`, note: "No verified score available", icon: Shield, tone: "green" }
  ];

  return <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
    {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <Link className="brand" href="/" aria-label="Vyrnexis home">
        <span className="brand-symbol"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 4 29.5 10.5v13L18 30 6.5 23.5v-13L18 4Z"/><path d="m11 18 4.5 4.5L25 13M18 4v8m11.5-1.5-7 4m-16 0 7 4M18 30v-8"/><circle cx="18" cy="12" r="2"/><circle cx="23.5" cy="14.5" r="2"/><circle cx="13" cy="18" r="2"/></svg></span>
        <span className="brand-copy"><strong>VYRNEXIS</strong><small>INTELLIGENCE PLATFORM</small></span>
        <button className="mobile-close" aria-label="Close navigation" onClick={(event) => { event.preventDefault(); setMobileNav(false); }}><X size={17}/></button>
      </Link>
      <div className="workspace-switch"><span className="workspace-avatar">{(data?.organization.name || principal?.organization.name || "V").slice(0,1)}</span><span className="workspace-text"><strong>{data?.organization.name || principal?.organization.name || "Workspace"}</strong><small>Enterprise edition</small></span><ChevronDown size={14}/></div>
      <div className="side-search"><Search size={14}/><input value={sideSearch} onChange={(event) => setSideSearch(event.target.value)} placeholder="Find a module" aria-label="Find a module"/><kbd>/</kbd></div>
      <nav className="navigation" aria-label="Main navigation">{filteredNavigation.map((section) => <section key={section.group} className="nav-section"><div className="nav-label">{section.group}</div>{section.items.map(([label, Icon, href]) => <Link key={label} href={href} className={pathname === href || (href !== "/" && pathname.startsWith(href)) ? "nav-link selected" : "nav-link"}><Icon size={16}/><span>{label}</span>{label === "Incidents" && !!data?.active_incidents && <b className="nav-count">{data.active_incidents}</b>}</Link>)}</section>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-status"><span className="live-dot"/><span><strong>API connection</strong><small>{error ? "Needs attention" : data ? "Connected" : "Checking status"}</small></span></div><Link className="nav-link" href="/platform/settings"><CircleHelp size={16}/><span>Help & documentation</span></Link><div className="profile"><div className="profile-avatar">{initials}</div><span><strong>{principal?.user.name || "Workspace user"}</strong><small>{principal?.user.role.replaceAll("_", " ") || "Signed in"}</small></span><button className="profile-action" type="button" aria-label="Sign out" title="Sign out" onClick={() => void signOut()}><LogOut size={15}/></button></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="top-left"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileNav(true)}><Menu size={18}/></button><button className="desktop-collapse icon-button" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setCollapsed((value) => !value)}><Menu size={16}/></button><div className="breadcrumb"><span>Command</span><span className="crumb-sep">/</span><strong>Overview</strong></div></div><div className="top-tools"><button className="global-search" onClick={() => { setPaletteOpen(true); setCommandSearch(""); }}><Search size={15}/><span>Search anything</span><kbd><Command size={10}/> K</kbd></button><div className="environment"><span className="environment-dot"/>{data?.organization.name.toLowerCase().includes("demonstration") ? "SYNTHETIC DEMO" : "DEVELOPMENT"}</div><span className="top-divider"/><div className="freshness"><span className={data ? "fresh-dot" : "fresh-dot idle"}/><span>{updated ? `Updated ${formatTime(updated.toISOString())}` : "Awaiting data"}</span></div><button className="icon-button theme-toggle" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => changeTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "☾" : "☀"}</button><Link className="icon-button" href="/platform/notifications" aria-label={`${unreadNotifications} unread notifications`}><Bell size={17}/>{unreadNotifications > 0 && <i/>}</Link><div className="profile-menu-wrap"><button className="user-chip" aria-label={principal?.user.name || "Signed-in user"} aria-expanded={profileOpen} onClick={() => setProfileOpen((value) => !value)}>{initials}</button>{profileOpen && <div className="profile-menu"><strong>{principal?.user.name}</strong><span>{principal?.user.email}</span><Link href="/platform/settings">Organization settings</Link><button type="button" onClick={() => void signOut()}>Sign out</button></div>}</div></div></header>

      <div className="content-area">
        <div className="page-title-row"><div><div className="eyebrow">OPERATIONAL INTELLIGENCE <span>|</span> {data?.organization.name || "ORGANIZATION WORKSPACE"}</div><h1>Command center</h1><p>Evidence-backed visibility across security and business operations.</p></div><div className="page-actions"><button className="outline-button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/><span>Refresh</span></button><button className="primary-button" onClick={() => window.location.href="/platform/incidents"}><Plus size={15}/> New investigation</button></div></div>

        {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Live data is not configured</strong><span>{error}</span></div><Link href="/login">Sign in</Link></div>}

        <section className="metrics-grid" aria-label="Organization metrics">{metricItems.map(({label,value,note,icon:Icon,tone})=><article className="metric-card" key={label}><div className="metric-top"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={15}/></span></div><div className="metric-number">{value ?? <span className="skeleton"/>}</div><div className="metric-foot"><span>{note}</span>{label === "Active incidents" && typeof value === "number" && <span className="metric-indicator"><ArrowUpRight size={13}/> Live</span>}</div></article>)}</section>

        {data?.investigations && <section className="panel investigation-overview" aria-label="Investigation operations">
          <div><h2>Investigation operations</h2><p>Case workload and agent task state</p></div>
          <Link href="/platform/forensics"><strong>{data.investigations.open_cases}</strong> open cases <small>{data.investigations.assigned_cases} assigned to you</small></Link>
          <Link href="/platform/nexus"><strong>{data.investigations.active_tasks}</strong> active tasks <small>{data.investigations.completed_tasks} completed · {data.investigations.failed_tasks} failed or timed out</small></Link>
          <Link href="/platform/nexus"><strong>{data.investigations.pending_reviews}</strong> awaiting human review</Link>
        </section>}
        {!!data?.activity?.length && <DashboardActivity key={data.organization.id} activity={data.activity} />}
        <section className="primary-grid">
          <article className="panel graph-panel"><div className="panel-heading"><div><div className="panel-kicker">VNIF / RELATIONSHIPS</div><h2>Intelligence fabric</h2></div><Link href="/platform/graph" className="subtle-link">Open graph <ArrowUpRight size={13}/></Link></div>
            {entities.length > 0 ? <div className="graph-stage"><svg className="graph-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Recorded intelligence relationships">{(data?.recent_relationships || []).map((edge)=>{const positions=[[16,24],[86,23],[15,70],[86,70],[50,16],[50,84]];const from=entities.slice(0,6).findIndex((entity)=>entity.id===edge.source_id);const to=entities.slice(0,6).findIndex((entity)=>entity.id===edge.target_id);if(from<0||to<0)return null;return <line key={edge.id} x1={positions[from][0]} y1={positions[from][1]} x2={positions[to][0]} y2={positions[to][1]}><title>{`${edge.source} ${edge.relationship_type} ${edge.target} | confidence ${edge.confidence}`}</title></line>;})}</svg><div className="graph-center"><span><Network size={20}/></span><strong>{data?.intelligence_relationships || 0}</strong><small>relationships</small></div><div className="entity-orbit">{entities.slice(0,6).map((entity,index)=><div className={`entity-node entity-${index}`} key={entity.id} title={`${entity.entity_type}: ${entity.display_name}`}><span>{entity.entity_type.slice(0,3).toUpperCase()}</span><strong>{entity.display_name}</strong></div>)}</div><div className="graph-legend"><span><i className="legend-cyan"/>Entities</span><span><i className="legend-blue"/>Stored relationships</span><small>Showing up to 6 recent entities</small></div></div> : <div className="empty-graph"><div className="empty-orbit"><Network size={23}/></div><strong>No intelligence graph data yet</strong><span>Entities and their recorded relationships will appear here.</span><Link href="/platform/graph">Explore intelligence graph <ArrowUpRight size={13}/></Link></div>}
          </article>
          <article className="panel posture-panel"><div className="panel-heading"><div><div className="panel-kicker">ORGANIZATION SNAPSHOT</div><h2>Intelligence inventory</h2></div><span className="source-chip">LIVE API</span></div><div className="inventory-list"><div className="inventory-item"><span className="inventory-icon blue"><Boxes size={16}/></span><div><strong>Entities</strong><small>Persistent intelligence records</small></div><b>{data?.intelligence_entities ?? " - "}</b></div><div className="inventory-item"><span className="inventory-icon cyan"><Network size={16}/></span><div><strong>Relationships</strong><small>Recorded correlations</small></div><b>{data?.intelligence_relationships ?? " - "}</b></div><div className="inventory-item"><span className="inventory-icon red"><AlertTriangle size={16}/></span><div><strong>Open incidents</strong><small>Not marked as closed</small></div><b>{data?.active_incidents ?? " - "}</b></div></div><div className="inventory-note"><ShieldCheck size={15}/><span>Scores and predictions remain hidden until supported by configured data.</span></div></article>
        </section>

        <section className="panel incidents-panel"><div className="panel-heading incident-heading"><div><div className="panel-kicker">INVESTIGATE</div><h2>Priority incident queue <span className="table-count">{data?.active_incidents ?? " - "}</span></h2></div><Link className="subtle-link" href="/platform/incidents">View all incidents <ArrowUpRight size={13}/></Link></div><div className="table-toolbar"><div className="table-search"><Search size={14}/><input id="incident-search" placeholder="Filter by incident, ID, or status" value={search} onChange={(event)=>setSearch(event.target.value)}/></div><div className="table-filters"><label htmlFor="severity-filter">Severity</label><select id="severity-filter" value={filter} onChange={(event)=>setFilter(event.target.value)}><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></div></div><div className="table-wrap"><table className="incident-table"><thead><tr><th>INCIDENT</th><th>SEVERITY</th><th>STATUS</th><th>RECORDED</th><th aria-label="Open incident"/></tr></thead><tbody>{incidents.map((incident)=><tr key={incident.id}><td><div className="incident-name"><span className="incident-glyph"><AlertTriangle size={14}/></span><span><strong>{incident.title}</strong><small className="mono">{incident.id}</small></span></div></td><td><span className={`severity ${incident.severity.toLowerCase()}`}><i/>{incident.severity}</span></td><td><span className="status-pill">{incident.status}</span></td><td className="mono muted-cell">{incident.created_at ? <time dateTime={incident.created_at}>{new Date(incident.created_at).toLocaleString()}</time> : "—"}</td><td><Link className="row-arrow" href={`/platform/incidents?id=${encodeURIComponent(incident.id)}`} aria-label={`Open ${incident.title}`}><ArrowUpRight size={13}/></Link></td></tr>)}{incidents.length===0&&<tr><td colSpan={5}><div className="table-empty">{data?.recent_incidents.length ? "No incidents match these filters." : "No incidents recorded for this organization."}</div></td></tr>}</tbody></table></div><div className="table-footer"><span>Showing {incidents.length} of {data?.recent_incidents.length ?? 0} recent incidents</span><Link href="/platform/incidents">Open incident manager <ArrowUpRight size={13}/></Link></div></section>

        <div className="bottom-grid"><section className="panel activity-panel"><div className="panel-heading"><div><div className="panel-kicker">SYSTEM STATUS</div><h2>Service connectivity</h2></div><span className={data ? "status-online" : "status-offline"}><i/>{data?"Connected":"Unavailable"}</span></div><div className="service-row"><span className="service-mark api-mark">API</span><div><strong>Vyrnexis API</strong><small>Dashboard and organization records</small></div><span className={data?"service-state healthy":"service-state pending"}>{data?"HEALTHY":"NOT CONNECTED"}</span></div><div className="service-row"><span className="service-mark db-mark">DB</span><div><strong>Organization data</strong><small>{data?.database === "postgresql" ? "PostgreSQL" : data?.database === "sqlite" ? "SQLite" : "Authorized organization store"}</small></div><span className={data?"service-state healthy":"service-state pending"}>{data?"AVAILABLE":"UNKNOWN"}</span></div></section>
        <section className="panel briefing-panel"><div className="panel-heading"><div><div className="panel-kicker">INTELLIGENCE BRIEFING</div><h2>Operational context</h2></div><span className="source-chip">RULE BASED</span></div><div className="briefing-body"><div className="briefing-symbol"><Activity size={17}/></div><div><strong>{data ? `${data.active_incidents} active incident${data.active_incidents===1?"":"s"} in view` : "Waiting for organization data"}</strong><p>{data ? `${data.intelligence_entities} entities and ${data.intelligence_relationships} recorded relationships are available. No causal claims are inferred from correlation records.` : "Configure a demo organization or sign in to load authorized operational records."}</p></div></div><div className="briefing-foot"><span>Generated from API records</span><span>{updated ? formatTime(updated.toISOString()) : "No data"}</span></div></section></div>
        <footer className="page-footer"><span>VYRNEXIS AI <b>|</b> Intelligence Beyond Detection</span><span>Enterprise Intelligence Platform <b>|</b> Development environment</span></footer>
      </div>
    </main>
    {paletteOpen && <div className="command-overlay" role="presentation" onMouseDown={(event)=>{if(event.target===event.currentTarget)setPaletteOpen(false);}}><section className="command-dialog" role="dialog" aria-modal="true" aria-labelledby="command-title"><div className="command-input-row"><Search size={17}/><input autoFocus id="command-title" aria-label="Search modules and incidents" placeholder="Search modules and incidents..." value={commandSearch} onChange={(event)=>setCommandSearch(event.target.value)}/><button onClick={()=>setPaletteOpen(false)} aria-label="Close command palette"><X size={15}/></button><kbd>ESC</kbd></div><div className="command-results" role="listbox" aria-label="Command results">{commandItems.length ? commandItems.slice(0,12).map((item)=><button className="command-result" key={`${item.title}-${item.href}`} role="option" aria-selected="false" onClick={()=>{setPaletteOpen(false);window.location.href=item.href;}}><span><item.icon size={15}/></span><strong>{item.title}</strong><small>{item.detail}</small><ArrowUpRight size={13}/></button>) : <div className="command-empty">No authorized modules or recent incidents match.</div>}</div><div className="command-footer"><span><kbd>Ctrl</kbd> <kbd>K</kbd> Open command palette</span><span>Results respect your role and organization</span></div></section></div>}
  </div>;
}
