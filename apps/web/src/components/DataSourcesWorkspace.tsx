"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { displayDate, intake, jsonRequest } from "@/lib/intake";

type Kind = "security" | "commerce" | "assets";
type Source = { id: string; name: string; kind: Kind; active: boolean; last_accepted_at: string | null };
type BatchRow = { row: number; status: string; errors?: string[]; record_id?: string };
type Batch = { id: string; status: string; accepted: number; duplicate: number; rejected: number; created_at: string; results?: BatchRow[] };
type Key = { id: string; label: string; expires_at: string; revoked_at: string | null };
const labels = { security: "Security events", commerce: "Payments and refunds", assets: "Asset inventory" };

export default function DataSourcesWorkspace() {
  const [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState("");
  const [role, setRole] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("security");
  const [file, setFile] = useState<File | null>(null);
  const [uploadKey, setUploadKey] = useState("");
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [keyLabel, setKeyLabel] = useState("");
  const [issuedKey, setIssuedKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const admin = ["owner", "organization_admin"].includes(role);
  const scopedKinds: Kind[] = admin ? ["security", "commerce", "assets"]
    : role === "security_analyst" ? ["security", "assets"] : role === "business_analyst" ? ["commerce"] : [];
  const source = sources.find(item => item.id === selected);
  const canUpload = Boolean(source?.active && scopedKinds.includes(source.kind));

  const loadSources = useCallback(async (signal?: AbortSignal) => {
    const items = await intake<Source[]>("data-sources", { signal });
    if (signal?.aborted) return;
    setSources(items);
    setSelected(previous => previous || items[0]?.id || "");
  }, []);

  const loadDetails = useCallback(async (id: string, allowKeys: boolean, signal?: AbortSignal) => {
    const [history, credentials] = await Promise.all([
      intake<Batch[]>(`data-sources/${id}/batches`, { signal }),
      allowKeys ? intake<Key[]>(`data-sources/${id}/keys`, { signal }) : Promise.resolve([]),
    ]);
    if (!signal?.aborted) { setBatches(history); setKeys(credentials); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([loadSources(controller.signal), fetch("/api/auth/session", { signal: controller.signal })
      .then(async response => {
        if (!response.ok) return;
        const identity = await response.json();
        if (!controller.signal.aborted) {
          setRole(identity.user.role);
          if (identity.user.role === "business_analyst") setKind("commerce");
        }
      })]).catch(cause => { if (!controller.signal.aborted) setError(cause.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loadSources]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    void loadDetails(selected, admin, controller.signal)
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected, admin, loadDetails]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await action(); } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Data source request failed.");
    } finally { setBusy(false); }
  }

  function choose(id: string) {
    setSelected(id);
    setBatch(null);
    setBatches([]);
    setKeys([]);
    setIssuedKey("");
    setFile(null);
    setUploadKey("");
  }

  async function upload() {
    if (!file || !source) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".csv") && !lower.endsWith(".json")) throw new Error("Choose a CSV or JSON file.");
    if (file.size > 512 * 1024) throw new Error("Uploads are limited to 512 KiB.");
    const report = await intake<Batch>(`data-sources/${source.id}/batches`, {
      method: "POST", body: file, headers: {
        "content-type": lower.endsWith(".csv") ? "text/csv" : "application/json",
        "idempotency-key": uploadKey,
      },
    });
    setBatch(report);
    await Promise.all([loadSources(), loadDetails(source.id, admin)]);
  }

  return <main className="intake-page">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Data sources</h1><p>Upload authorized records and inspect what the system accepted.</p></div><Link className="agents-refresh" href="/platform/fraud">Fraud intelligence</Link></header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    <div className="intake-layout">
      <section className="panel intake-panel" aria-label="Source inventory">
        <h2>Source inventory</h2>
        {loading && <p role="status">Loading sources…</p>}
        {!loading && !sources.length && !error && <p>No sources have been configured.</p>}
        <div className="intake-list">{sources.map(item => <button type="button" key={item.id} aria-pressed={selected === item.id} disabled={busy} onClick={() => { if (selected !== item.id) choose(item.id); }}>
          <strong>{item.name}</strong><small>{labels[item.kind]} · {item.last_accepted_at ? "Data received" : "Awaiting first batch"}</small>
        </button>)}</div>
        {scopedKinds.length > 0 && <form className="detection-form" onSubmit={event => {
          event.preventDefault();
          void run(async () => {
            const created = await intake<Source>("data-sources", jsonRequest("POST", { name, kind }));
            setName(""); await loadSources(); choose(created.id);
          });
        }}>
          <label>Source name<input required minLength={2} maxLength={100} value={name} onChange={event => setName(event.target.value)}/></label>
          <label>Record category<select value={kind} onChange={event => setKind(event.target.value as Kind)}>
            {scopedKinds.map(value => <option key={value} value={value}>{labels[value]}</option>)}
          </select></label>
          <button className="primary-button" disabled={busy}>Add source</button>
        </form>}
      </section>
      {source && <section className="panel intake-panel" aria-label="Selected source">
        <h2>{source.name}</h2>
        <p>{source.last_accepted_at ? `Last accepted batch ${displayDate(source.last_accepted_at)}.` : "No records received."} This source accepts submitted batches.</p>
        {canUpload && <form key={source.id} className="detection-form" onSubmit={event => { event.preventDefault(); void run(upload); }}>
          <label>CSV or JSON file (512 KiB maximum)<input required type="file" accept=".csv,.json,text/csv,application/json" onChange={event => {
            setFile(event.target.files?.[0] || null); setUploadKey(crypto.randomUUID());
          }}/></label>
          <button className="primary-button" disabled={!file || busy}>{busy ? "Working…" : "Submit batch"}</button>
        </form>}
        <details className="detection-history"><summary>Schema version 1</summary>
          <p>JSON uses <code>{'{ "version": 1, "records": [...] }'}</code>. CSV requires <code>schema_version,record_type,external_id,occurred_at</code>. Every timestamp must include a timezone.</p>
          <ul>
            <li>Security · <code>security</code> with <code>event_type</code> and <code>title</code>. Include <code>account</code>, <code>device</code>, and <code>outcome</code> for authentication detection.</li>
            <li>Commerce · <code>payment</code> or <code>refund</code> with <code>account</code>, <code>currency</code>, and <code>amount_minor</code>.</li>
            <li>Assets · <code>asset</code> with <code>name</code> and <code>asset_type</code>.</li>
          </ul>
        </details>
        <h3>Batch history</h3>
        {!batches.length && <p>No batches recorded.</p>}
        <div className="intake-list">{batches.map(item => <button key={item.id} type="button" aria-pressed={item.id === batch?.id} disabled={busy}
          onClick={() => void run(async () => setBatch(await intake<Batch>(`data-sources/${source.id}/batches/${item.id}`)))}>
          <strong>{displayDate(item.created_at)} · {item.status}</strong><small>{item.accepted} accepted · {item.duplicate} duplicates · {item.rejected} rejected</small>
        </button>)}</div>
        {batch?.results && <section className="intake-results" aria-label="Row results"><h3>Row results</h3>
          <ol>{batch.results.map(row => <li key={row.row}><strong>Row {row.row} · {row.status}</strong>{row.errors && <p>{row.errors.join(" · ")}</p>}</li>)}</ol>
        </section>}
      </section>}
      {source && admin && <aside className="panel intake-panel">
        <h2>Webhook keys</h2>
        <p>Keys expire after 30 days and submit only to this source. Use the <code>X-Ingestion-Key</code> and <code>Idempotency-Key</code> headers.</p>
        <code className="intake-endpoint">POST /api/v1/ingestion/webhooks/{source.id}</code>
        <form className="detection-form" onSubmit={event => {
          event.preventDefault();
          void run(async () => {
            const created = await intake<Key & { key: string }>(`data-sources/${source.id}/keys`, jsonRequest("POST", { label: keyLabel }));
            setIssuedKey(created.key); setKeyLabel(""); await loadDetails(source.id, admin);
          });
        }}>
          <label>Key label<input value={keyLabel} onChange={event => setKeyLabel(event.target.value)} minLength={2} maxLength={100} required/></label>
          <button className="agents-refresh" disabled={busy}>Issue source key</button>
        </form>
        {issuedKey && <div className="intake-secret"><p>Copy this key now. It is shown once.</p><code>{issuedKey}</code>
          <button type="button" className="agents-refresh" onClick={() => setIssuedKey("")}>Hide key</button></div>}
        <ul className="detection-sources">{keys.map(key => <li key={key.id}><strong>{key.label}</strong><small>{key.revoked_at ? "Revoked" : `Expires ${displayDate(key.expires_at)}`}</small>
          {!key.revoked_at && <button className="agents-refresh" type="button" disabled={busy} onClick={() => void run(async () => {
            await intake(`data-sources/${source.id}/keys/${key.id}/revoke`, { method: "POST" });
            setIssuedKey(""); await loadDetails(source.id, admin);
          })}>Revoke key</button>}</li>)}</ul>
      </aside>}
    </div>
  </main>;
}
