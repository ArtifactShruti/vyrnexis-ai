"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, FileText, RefreshCw, Search } from "lucide-react";
import { workspace } from "@/lib/ai-workspace";

type Report = {
  id: string;
  title: string;
  category: string;
  source_module: string;
  source_id: string | null;
  source_refs: unknown[];
  version: number;
  status: string;
  review_status: string;
  integrity_hash: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
};

type ReportPage = { items: Report[]; total: number; limit: number; offset: number };
type ReportDetail = Report & { snapshot: Record<string, unknown> };

const categories = ["forensic", "investigation", "security", "threat", "fraud", "commerce", "business", "workflow", "digital_twin", "copilot", "asset", "incident"];
const sources = ["forensics", "nexus", "security", "threat_intelligence", "fraud", "ecommerce", "business_intelligence", "workflow", "digital_twin", "copilot", "assets", "incidents"];

export default function ReportsWorkspace() {
  const [page, setPage] = useState<ReportPage>({ items: [], total: 0, limit: 100, offset: 0 });
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [category, setCategory] = useState("");
  const [source, setSource] = useState("");
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState(false);
  const [title, setTitle] = useState("");
  const [newCategory, setNewCategory] = useState("security");
  const [newSource, setNewSource] = useState("security");
  const [sourceId, setSourceId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (category) params.set("category", category);
      if (source) params.set("source_module", source);
      if (search) params.set("search", search);
      setPage(await workspace<ReportPage>(`reports?${params}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Reports are unavailable.");
    } finally {
      setBusy(false);
    }
  }, [category, source, search]);

  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => page.items, [page.items]);

  const inspect = async (id: string) => {
    setError("");
    try {
      setSelected(await workspace<ReportDetail>(`reports/${id}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Report preview is unavailable.");
    }
  };

  const generate = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await workspace<Report>("reports", {
        method: "POST",
        body: JSON.stringify({
          title,
          category: newCategory,
          source_module: newSource,
          source_id: sourceId.trim() || null,
        }),
      });
      setDialog(false);
      setTitle("");
      setSourceId("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Report could not be generated.");
    } finally {
      setBusy(false);
    }
  };

  return <main className="module-page reports-page">
    <header className="module-heading"><div><div className="eyebrow">DOCUMENT INTELLIGENCE</div><h1>Reports center</h1><p>Tenant-scoped report snapshots generated from authorized persisted records.</p></div><div className="module-actions"><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button><button className="primary-button" type="button" onClick={() => setDialog(true)}><FileText size={15}/>Generate report</button></div></header>
    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Reports request failed</strong><span>{error}</span></div></div>}
    <section className="reports-layout">
      <aside className="panel reports-filters"><div className="panel-kicker">REPORT FILTERS</div><label>Search<div className="table-search"><Search size={14}/><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Report title"/></div></label><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item}>{item}</option>)}</select></label><label>Source module<select value={source} onChange={(event) => setSource(event.target.value)}><option value="">All sources</option>{sources.map((item) => <option key={item}>{item}</option>)}</select></label></aside>
      <section className="panel reports-inventory"><div className="panel-heading"><div><div className="panel-kicker">REPORT INVENTORY</div><h2>{page.total} registered reports</h2></div></div>{visible.length === 0 ? <div className="module-empty"><FileText size={22}/><strong>No reports registered</strong><span>Generate a report from an authorized persisted source.</span></div> : <div className="table-wrap"><table className="module-table"><thead><tr><th>Report</th><th>Source</th><th>Version</th><th>Review</th><th>Created</th><th>Action</th></tr></thead><tbody>{visible.map((row) => <tr key={row.id}><td><strong>{row.title}</strong><small>{row.category}</small></td><td>{row.source_module}</td><td>v{row.version}</td><td>{row.review_status}</td><td>{new Date(row.created_at).toLocaleString()}</td><td><button className="outline-button" type="button" onClick={() => void inspect(row.id)}>Preview</button></td></tr>)}</tbody></table></div>}</section>
      {selected && <aside className="panel reports-inspector"><div className="panel-heading"><div><div className="panel-kicker">SELECTED REPORT</div><h2>{selected.title}</h2></div><button className="outline-button" type="button" onClick={() => setSelected(null)}>Close</button></div><dl><div><dt>Source</dt><dd>{selected.source_module}</dd></div><div><dt>Version</dt><dd>v{selected.version}</dd></div><div><dt>Review</dt><dd>{selected.review_status}</dd></div><div><dt>Integrity SHA-256</dt><dd className="report-hash">{selected.integrity_hash}</dd></div></dl><pre className="report-preview">{JSON.stringify(selected.snapshot, null, 2)}</pre><div className="report-actions"><a className="primary-button" href={`/api/workspace/reports/${selected.id}/export?format=json`}><Download size={14}/>JSON</a><a className="outline-button" href={`/api/workspace/reports/${selected.id}/export?format=csv`}>CSV</a></div></aside>}
    </section>
    {dialog && <div className="module-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(false); }}><form className="module-dialog" onSubmit={generate}><div className="panel-heading"><div><div className="panel-kicker">NEW SNAPSHOT</div><h2>Generate report</h2></div><button type="button" className="icon-button" onClick={() => setDialog(false)}>×</button></div><label>Title<input required minLength={2} maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)}/></label><label>Category<select value={newCategory} onChange={(event) => setNewCategory(event.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select></label><label>Source module<select value={newSource} onChange={(event) => setNewSource(event.target.value)}>{sources.map((item) => <option key={item}>{item}</option>)}</select></label><label>Source record ID<input value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="Required for forensics, Nexus, and Copilot"/></label><button className="primary-button" type="submit" disabled={busy}>Generate snapshot</button></form></div>}
  </main>;
}
