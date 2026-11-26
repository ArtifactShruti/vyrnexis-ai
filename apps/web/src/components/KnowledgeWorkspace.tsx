"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Citation, request, workspace } from "@/lib/ai-workspace";

type Document = { id: string; title: string; visibility: "private" | "organization"; status: string; version: number;
  can_manage: boolean; expires_at: string | null };
type Detail = Document & { versions: { version: number; filename: string; sha256: string; created_at: string }[] };
type Embedding = { enabled: boolean; status: string; chunks: number; error: string | null };
const root = "knowledge/documents";

async function encoded(file: File) {
  if (file.size === 0 || file.size > 2 * 1024 * 1024) throw new Error("Choose a file up to 2 MiB.");
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The selected file could not be read."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}

export default function KnowledgeWorkspace() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [detail, setDetail] = useState<Detail>();
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Citation[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [canUpload, setCanUpload] = useState(false);
  const [localEnabled, setLocalEnabled] = useState(false);
  const [index, setIndex] = useState<Embedding>();
  const [searchMode, setSearchMode] = useState<"keyword" | "hybrid">("keyword");
  const [searchMethod, setSearchMethod] = useState("");
  const indexing = index?.status === "queued";

  async function reload() { setDocuments(await workspace<Document[]>(root)); }
  useEffect(() => {
    setSelected(new URLSearchParams(window.location.search).get("document") || "");
    void reload().catch(cause => setError(cause.message)).finally(() => setLoading(false));
    void workspace<{ enabled: boolean }>("knowledge/embeddings/availability").then(value => setLocalEnabled(value.enabled)).catch(() => {});
    void fetch("/api/auth/session", { cache: "no-store" }).then(async response => {
      if (response.ok) setCanUpload(["owner", "organization_admin", "forensic_investigator", "security_analyst", "business_analyst"].includes((await response.json()).user.role));
    }).catch(() => {});
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(undefined);
    setIndex(undefined);
    if (selected) void workspace<Detail>(`${root}/${selected}`, { signal: controller.signal }).then(setDetail)
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected]);
  useEffect(() => {
    if (!localEnabled || !selected || !detail?.version) return;
    const controller = new AbortController();
    async function refresh() {
      try {
        const value = await workspace<Embedding>(`${root}/${selected}/embedding`, { signal: controller.signal });
        if (!controller.signal.aborted) setIndex(value);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Embedding status unavailable.");
      }
    }
    void refresh();
    const timer = indexing ? window.setInterval(() => void refresh(), 3000) : undefined;
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [detail?.version, indexing, localEnabled, selected]);

  async function act(run: () => Promise<void>) {
    setBusy(true); setError(""); setStatus("");
    try { await run(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Knowledge request failed."); }
    finally { setBusy(false); }
  }

  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Knowledge base</h1><p>Index authorized documents and retrieve source passages by keyword.</p></div><Link className="agents-refresh" href="/platform/copilot">Open Copilot</Link></header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    {status && <p className="agents-success" role="status">{status}</p>}
    <div className="intake-layout ai-layout">
      <section className="panel intake-panel"><h2>Documents</h2>
        {loading && <p role="status">Loading documents…</p>}
        {!loading && !documents.length && <p>No visible documents.</p>}
        <div className="intake-list">{documents.map(doc => <button key={doc.id} type="button" disabled={busy} aria-pressed={doc.id === selected}
          onClick={() => { setError(""); setSelected(doc.id); }}><strong>{doc.title}</strong><small>{doc.visibility} · {doc.status} · version {doc.version}</small></button>)}</div>
        {canUpload && <details className="detection-history"><summary>Index a document</summary>
          <form className="detection-form" onSubmit={event => {
            event.preventDefault(); const element = event.currentTarget; const fields = new FormData(element);
            void act(async () => {
              const file = fields.get("file") as File;
              const doc = await workspace<Document>(root, request("POST", { filename: file.name, content_base64: await encoded(file),
                title: fields.get("title"), visibility: fields.get("visibility"), retention_days: Number(fields.get("retention")) }));
              element.reset(); setSelected(doc.id); await reload(); setStatus("Document indexed.");
            });
          }}>
            <label>Title<input name="title" required maxLength={160}/></label>
            <label>File<input name="file" type="file" required accept=".txt,.md,.csv,.json,.pdf,.docx"/></label>
            <label>Visibility<select name="visibility"><option value="private">Private to your account</option><option value="organization">Organization</option></select></label>
            <label>Retention in days<input name="retention" type="number" min={1} max={365} defaultValue={90} required/></label>
            <button className="primary-button" disabled={busy}>{busy ? "Working…" : "Index document"}</button>
          </form>
        </details>}
      </section>
      <section className="panel intake-panel"><h2>Search passages</h2>
        <form className="detection-form" onSubmit={event => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const only = values.get("selected");
          void act(async () => {
            const params = new URLSearchParams({ query });
            if (only && selected) params.set("document_id", selected);
            const result = searchMode === "hybrid" ? await workspace<{ sources: Citation[]; method: string; reason?: string }>(
              "knowledge/search/hybrid", request("POST", { query, ...(only && selected ? { document_id: selected } : {}),
                acknowledge_local_processing: values.get("local_search") === "on" }),
            ) : await workspace<{ sources: Citation[]; method: string; reason?: string }>(`knowledge/search?${params}`);
            setHits(result.sources);
            setSearchMethod(result.reason ? `Keyword fallback · ${result.reason.replaceAll("_", " ")}` : `${result.method} retrieval`);
          });
        }}><label>Keywords<input value={query} onChange={event => setQuery(event.target.value)} minLength={2} maxLength={180} required/></label>
          {localEnabled && <label>Retrieval method<select value={searchMode} onChange={event => setSearchMode(event.target.value as "keyword" | "hybrid")}>
            <option value="keyword">Keyword</option><option value="hybrid">Keyword and local semantic search</option></select></label>}
          {searchMode === "hybrid" && <label className="ai-check"><input type="checkbox" name="local_search" required/> Send this query to the configured local model</label>}
          {selected && <label className="ai-check"><input type="checkbox" name="selected"/> Search selected document</label>}
          <button className="primary-button" disabled={busy}>Search</button>
        </form>
        {searchMethod && <p role="status">{searchMethod}</p>}
        {hits?.length === 0 && <p>No matching authorized passages.</p>}
        <ol className="detection-sources">{hits?.map(item => <li key={item.key}><button className="subtle-link" type="button"
          onClick={() => setSelected(item.document_id || "")}>{item.title}</button><small>Version {item.version} · {item.location}</small><p>{item.excerpt}</p></li>)}</ol>
      </section>
      <aside className="panel intake-panel" aria-label="Document details"><h2>Document details</h2>
        {!detail && <p>{selected ? "Select an available document to see its history." : "Select a document."}</p>}
        {detail && <><h3>{detail.title}</h3><p>{detail.visibility} · Expires {detail.expires_at ? new Date(detail.expires_at).toLocaleDateString() : "—"}</p>
          {index?.enabled && <p role="status">Local semantic index · {index.status.replaceAll("_", " ")} · {index.chunks} passages
            {index.error ? ` · ${index.error.replaceAll("_", " ")}` : ""}</p>}
          <ol className="detection-sources">{detail.versions.map(item => <li key={item.version}><strong>Version {item.version} · {item.filename}</strong><small className="ai-wrap">SHA-256 {item.sha256}</small></li>)}</ol>
          {detail.can_manage && canUpload && <>
            {localEnabled && index?.status === "not_indexed" && <form className="detection-form" key={detail.id + "-embedding"}
              onSubmit={event => {
                event.preventDefault(); const values = new FormData(event.currentTarget);
                void act(async () => setIndex(await workspace<Embedding>(`${root}/${detail.id}/embedding`,
                  request("POST", { acknowledge_local_processing: values.get("local_document") === "on" }))));
              }}>
              <label className="ai-check"><input type="checkbox" name="local_document" required/> Send this version to the configured local embedding model</label>
              <button className="agents-refresh" disabled={busy}>Build semantic index</button>
            </form>}
            <form className="detection-form" key={detail.id} onSubmit={event => {
              event.preventDefault(); const element = event.currentTarget; const file = new FormData(element).get("file") as File;
              void act(async () => {
                await workspace(`${root}/${detail.id}/versions`, request("POST", { filename: file.name, content_base64: await encoded(file) }));
                setDetail(await workspace<Detail>(`${root}/${detail.id}`)); element.reset(); await reload(); setStatus("Version indexed.");
              });
            }}><label>New version<input name="file" type="file" required accept=".txt,.md,.csv,.json,.pdf,.docx"/></label><button className="agents-refresh" disabled={busy}>Index version</button></form>
            <details className="detection-history"><summary>Access and retention</summary><form className="detection-form" key={detail.id + detail.visibility}
              onSubmit={event => {
                event.preventDefault(); const fields = new FormData(event.currentTarget);
                void act(async () => {
                  await workspace(`${root}/${detail.id}/policy`, request("PUT", { visibility: fields.get("visibility"), retention_days: Number(fields.get("retention")) }));
                  setDetail(await workspace<Detail>(`${root}/${detail.id}`)); await reload(); setStatus("Document policy saved.");
                });
              }}><label>Visibility<select name="visibility" defaultValue={detail.visibility}><option value="private">Private</option><option value="organization">Organization</option></select></label>
              <label>Retention from today<input name="retention" type="number" min={1} max={365} defaultValue={90} required/></label><button className="agents-refresh" disabled={busy}>Save policy</button>
            </form></details>
          </>}
        </>}
        {canUpload && documents.find(doc => doc.id === selected)?.can_manage && <button className="agents-refresh" type="button" disabled={busy}
          onClick={() => { if (window.confirm("Permanently delete this document and its indexed versions?"))
            void act(async () => { await workspace(`${root}/${selected}`, { method: "DELETE" }); setSelected(""); setHits(null); await reload(); setStatus("Document deleted."); }); }}>
          Delete document
        </button>}
      </aside>
    </div>
  </main>;
}
