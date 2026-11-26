"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { caseAdmins, caseWriters, forensic, forensicBody, localTime, sessionRole } from "@/lib/forensic";
import EvidenceImageMetadata, { type ImageMetadata } from "@/components/EvidenceImageMetadata";

type Case = { id: string; title: string; description: string; priority: string; status: string; investigator_id: string | null; investigator_name: string | null; team: string | null; version: number; updated_at: string };
type Reference = { kind: string; object_id: string };
type Note = { id: string; revision: number; category: string; body: string; time: string; author_id: string; references: Reference[] };
type Evidence = { id: string; name: string; original_filename: string | null; classification: string; size_bytes: number | null; signature: string | null; custodian_id: string | null; sha256: string; sha512: string; sequence: number; archived: boolean; tags: string[]; image_metadata: ImageMetadata | null };
type Detail = Case & { links: Reference[]; notes: Note[]; evidence: Evidence[]; activity: { action: string; time: string; actor_id: string | null }[] };
type Report = { id: string; version: number; created_at: string; integrity_hash: string };
type Custody = { chain_status: string; events: { sequence: number; time: string; action: string; actor_id: string; previous_custodian_id: string | null; new_custodian_id: string | null; purpose: string; integrity_hash: string }[] };
type Investigator = { id: string; name: string };
const root = "forensic-cases";
const caseTransitions: Record<string, string[]> = { open: ["investigating"], investigating: ["review"], review: ["investigating", "closed"], closed: ["investigating"] };

function Options({ items }: { items: string[] }) {
  return <>{items.map(item => <option key={item} value={item}>{item}</option>)}</>;
}

export default function ForensicsWorkspace() {
  const [role, setRole] = useState("");
  const [staff, setStaff] = useState<Investigator[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [custody, setCustody] = useState<Custody | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("recent");
  const [assigned, setAssigned] = useState(false);
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const isWriter = caseWriters.includes(role);
  const isAdmin = caseAdmins.includes(role);
  const activeEvidence = detail?.evidence.find(item => item.id === selectedEvidence);
  const writable = isWriter && detail?.status !== "closed";
  const base = `${root}/${selected}`;

  const loadList = useCallback(async (signal?: AbortSignal) => {
    const params = new URLSearchParams({ query, sort, assigned: String(assigned), offset: String(offset) });
    if (filter) params.set("status", filter);
    const result = await forensic<{ items: Case[]; next_offset: number | null }>(`${root}?${params}`, { signal });
    if (!signal?.aborted) { setCases(result.items); setNext(result.next_offset); }
  }, [query, filter, sort, assigned, offset]);

  const loadDetail = useCallback(async (id: string, signal?: AbortSignal) => {
    const [data, stored] = await Promise.all([
      forensic<Detail>(`${root}/${id}`, { signal }), forensic<Report[]>(`${root}/${id}/reports`, { signal }),
    ]);
    if (!signal?.aborted) { setDetail(data); setReports(stored); }
  }, []);

  const loadCustody = useCallback(async (caseId: string, evidenceId: string, signal?: AbortSignal) => {
    const data = await forensic<Custody>(`${root}/${caseId}/evidence/${evidenceId}/custody`, { signal });
    if (!signal?.aborted) setCustody(data);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const caseId = new URLSearchParams(window.location.search).get("case");
    if (caseId) setSelected(caseId);
    void Promise.all([sessionRole(controller.signal), forensic<Investigator[]>(`${root}/investigators`, { signal: controller.signal })])
      .then(([value, people]) => { if (!controller.signal.aborted) { setRole(value); setStaff(people); } })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void loadList(controller.signal).catch(cause => { if (!controller.signal.aborted) setError(cause.message); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 160);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [loadList]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    void loadDetail(selected, controller.signal).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected, loadDetail]);
  useEffect(() => {
    if (!selected || !selectedEvidence) return;
    const controller = new AbortController();
    void loadCustody(selected, selectedEvidence, controller.signal).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected, selectedEvidence, loadCustody]);

  function choose(id: string) {
    if (id === selected) return;
    setSelected(id); setDetail(null); setSelectedEvidence(""); setCustody(null); setNote(null); setError("");
  }

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The case request did not complete.");
    } finally { setBusy(false); }
  }

  async function saveAction(action: string, payload?: object, method: "POST" | "PUT" = "POST") {
    await forensic(`${base}/${action}`, payload ? forensicBody(method, payload) : { method });
    await Promise.all([loadDetail(selected), loadList()]);
    if (selectedEvidence) await loadCustody(selected, selectedEvidence);
    setMessage("Case updated.");
  }

  async function exportEvidence(purpose: string) {
    if (!activeEvidence) return;
    const result = await fetch(`/api/forensic/${base}/evidence/${activeEvidence.id}/export`, forensicBody("POST", { purpose }));
    if (!result.ok) {
      const payload = await result.json();
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Evidence export was denied.");
    }
    const href = URL.createObjectURL(await result.blob());
    const file = document.createElement("a");
    file.href = href;
    file.download = activeEvidence.original_filename || activeEvidence.name;
    file.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    await Promise.all([loadDetail(selected), loadCustody(selected, activeEvidence.id)]);
    setMessage("Export recorded in custody history.");
  }

  return <main className="intake-page investigation-case">
    <Link href="/" className="subtle-link">← Command center</Link>
    <header className="intake-heading"><div><h1>Forensic laboratory</h1><p>Manage cases, preserve evidence custody, and export investigation reports.</p></div>
      <div className="intake-actions"><Link className="agents-refresh" href="/platform/evidence-vault">Evidence vault</Link><Link className="agents-refresh" href="/platform/nexus">Investigation Nexus</Link></div>
    </header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    {message && <p className="agents-success" role="status">{message}</p>}
    <div className="intake-layout forensic-layout">
      <aside className="panel intake-panel" aria-label="Find cases">
        <h2>Cases</h2>
        <div className="detection-form">
          <label>Search title or case ID<input maxLength={120} value={query} onChange={event => { setQuery(event.target.value); setOffset(0); }}/></label>
          <label>Status<select value={filter} onChange={event => { setFilter(event.target.value); setOffset(0); }}><option value="">Any status</option><Options items={["open", "investigating", "review", "closed"]}/></select></label>
          <label>Sort<select value={sort} onChange={event => { setSort(event.target.value); setOffset(0); }}><Options items={["recent", "oldest", "title"]}/></select></label>
          <label className="detection-checkbox"><input type="checkbox" checked={assigned} onChange={event => { setAssigned(event.target.checked); setOffset(0); }}/> Assigned to me</label>
        </div>
        {loading && <p role="status">Loading case list…</p>}
        {!loading && !cases.length && !error && <p>No cases match these filters.</p>}
        <div className="intake-list">{cases.map(item => <button type="button" key={item.id} aria-pressed={selected === item.id} disabled={busy} onClick={() => choose(item.id)}>
          <strong>{item.title}</strong><small>{item.priority} · {item.status}</small><small>{item.investigator_name || "Unassigned"}</small>
        </button>)}</div>
        <div className="intake-actions"><button className="agents-refresh" disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><button className="agents-refresh" disabled={next === null || busy} onClick={() => setOffset(next || 0)}>Next</button></div>
        {isWriter && <details className="detection-history"><summary>Create a case</summary>
          <form className="detection-form" onSubmit={event => {
            event.preventDefault();
            const form = event.currentTarget;
            const values = Object.fromEntries(new FormData(form));
            void act(async () => { const item = await forensic<Case>(root, forensicBody("POST", values)); form.reset(); choose(item.id); await loadList(); setMessage("Case created."); });
          }}>
            <label>Title<input name="title" minLength={3} maxLength={240} required/></label>
            <label>Category<select name="category"><Options items={["security", "fraud", "compliance", "other"]}/></select></label>
            <label>Priority<select name="priority" defaultValue="medium"><Options items={["low", "medium", "high", "critical"]}/></select></label>
            <label>Description<textarea name="description" minLength={3} maxLength={4000} required rows={3}/></label>
            <button className="primary-button" disabled={busy}>Create case</button>
          </form>
        </details>}
      </aside>
      <section className="panel intake-panel" aria-label="Case record">
        {!detail && <><h2>Case record</h2><p>{selected && !error ? "Loading case…" : "Select a case to see its investigation record."}</p></>}
        {detail && <>
          <h2>{detail.title}</h2><p>{detail.status} · {detail.priority} · {detail.investigator_name || "Unassigned"}{detail.team ? ` · ${detail.team}` : ""}</p>
          <p>{detail.description}</p><small>{detail.id}</small>
          {isAdmin && writable && <details className="detection-history"><summary>Assign investigator</summary>
            <form key={`assign-${detail.version}`} className="detection-form" onSubmit={event => {
              event.preventDefault(); const data = new FormData(event.currentTarget);
              void act(() => saveAction("assignment", { investigator_id: data.get("investigator_id") || null, team: data.get("team") || null, expected_version: detail.version }, "PUT"));
            }}>
              <label>Investigator<select name="investigator_id" defaultValue={detail.investigator_id || ""}><option value="">Unassigned</option>{staff.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
              <label>Team<input name="team" maxLength={120} defaultValue={detail.team || ""}/></label>
              <button className="agents-refresh" disabled={busy}>Save assignment</button>
            </form>
          </details>}
          {(writable || isAdmin && detail.status === "closed") && <details className="detection-history"><summary>Change case status</summary>
            <form key={`status-${detail.version}`} className="detection-form" onSubmit={event => {
              event.preventDefault();
              const data = Object.fromEntries(new FormData(event.currentTarget));
              void act(() => saveAction("transition", { ...data, expected_version: detail.version }));
            }}>
              <label>Next status<select name="status"><Options items={caseTransitions[detail.status] || []}/></select></label>
              <label>Reason or closure summary<textarea name="reason" minLength={3} maxLength={500} required rows={2}/></label>
              <small>Closing a case requires an assignee and a current review note.</small>
              <button className="agents-refresh" disabled={busy}>Apply status</button>
            </form>
          </details>}
          <h3>Related records</h3>
          {!detail.links.length && <p>No records are associated with this case.</p>}
          <ul className="detection-sources">{detail.links.map(ref => <li key={`${ref.kind}-${ref.object_id}`}><strong>{ref.kind}</strong>
            {ref.kind === "incident" ? <Link href={`/platform/incidents?id=${ref.object_id}`}>{ref.object_id}</Link>
             : ref.kind === "entity" ? <Link href={`/platform/graph?focus=${ref.object_id}`}>{ref.object_id}</Link>
             : <small>{ref.object_id}</small>}</li>)}</ul>
          {writable && <details className="detection-history"><summary>Link an incident, finding, or entity</summary><form className="detection-form" onSubmit={event => {
            event.preventDefault(); const form = event.currentTarget; const values = Object.fromEntries(new FormData(form));
            void act(async () => { await saveAction("links", values); form.reset(); });
          }}><label>Record type<select name="kind"><Options items={["incident", "finding", "entity"]}/></select></label><label>Record ID<input name="object_id" maxLength={120} required/></label><button className="agents-refresh" disabled={busy}>Link record</button></form></details>}
          <h3>Investigator notes</h3>
          {!detail.notes.length && <p>No notes have been entered.</p>}
          <ul className="detection-sources">{detail.notes.map(item => <li key={`${item.id}-${item.revision}`}>
            <strong>{item.category} · revision {item.revision}</strong><p className="forensic-note">{item.body}</p><small>{localTime(item.time)} · {staff.find(person => person.id === item.author_id)?.name || item.author_id}</small>
            {!!item.references.length && <small>{item.references.map(ref => `${ref.kind}: ${ref.object_id}`).join(" · ")}</small>}
            {writable && !detail.notes.some(other => other.id === item.id && other.revision > item.revision) && <button type="button" className="agents-refresh" disabled={busy} onClick={() => setNote(item)}>Create revision</button>}
          </li>)}</ul>
          {writable && <form key={note ? `${note.id}-${note.revision}` : "new-note"} className="detection-form" onSubmit={event => {
            event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
            const refs = data.getAll("references").map(value => detail.links[Number(value)]);
            const values = { body: data.get("body"), category: data.get("category"), references: refs };
            void act(async () => { await saveAction(note ? `notes/${note.id}/revisions` : "notes", note ? { ...values, expected_revision: note.revision } : values); setNote(null); form.reset(); });
          }}>
            <label>{note ? "Revision category" : "Note category"}<select name="category" defaultValue={note?.category || "observation"}><Options items={["observation", "hypothesis", "finding", "review"]}/></select></label>
            <label>Note body<textarea name="body" defaultValue={note?.body || ""} required minLength={3} maxLength={4000} rows={3}/></label>
            {!!detail.links.length && <label>Supporting references<select name="references" multiple size={Math.min(detail.links.length, 4)} defaultValue={detail.links.map((ref, index) => note?.references.some(item => item.kind === ref.kind && item.object_id === ref.object_id) ? String(index) : "").filter(Boolean)}>
              {detail.links.map((ref, index) => <option key={`${ref.kind}-${ref.object_id}`} value={index}>{ref.kind} · {ref.object_id}</option>)}</select></label>}
            <button className="agents-refresh" disabled={busy}>{note ? "Save revision" : "Add note"}</button>
            {note && <button type="button" className="agents-refresh" onClick={() => setNote(null)}>Cancel revision</button>}
          </form>}
          <h3>Reports and activity</h3>
          <div className="intake-actions">{isWriter && <button className="primary-button" disabled={busy} type="button" onClick={() => void act(() => saveAction("reports"))}>Create report version</button>}
            <Link className="agents-refresh" href={`/platform/nexus?case=${detail.id}`}>Analyze this case</Link></div>
          <ul className="detection-sources">{reports.map(report => <li key={report.id}><strong>Version {report.version} · {localTime(report.created_at)}</strong>
            <small>Snapshot SHA-256 {report.integrity_hash}</small><div className="intake-actions">
              <a className="agents-refresh" href={`/api/forensic/${base}/reports/${report.id}/pdf`}>PDF</a><a className="agents-refresh" href={`/api/forensic/${base}/reports/${report.id}/json`}>JSON</a>
            </div></li>)}</ul>
          <ol className="detection-sources">{detail.activity.map((item, index) => <li key={`${item.time}-${index}`}><strong>{item.action.replaceAll(".", " ")}</strong><small>{localTime(item.time)} · {item.actor_id || "system"}</small></li>)}</ol>
        </>}
      </section>
      <aside className="panel intake-panel" aria-label="Evidence and custody">
        <h2>Evidence and custody</h2>
        {detail && <>
          <div className="intake-list">{detail.evidence.map(item => <button key={item.id} type="button" aria-pressed={selectedEvidence === item.id} disabled={busy} onClick={() => {
            if (selectedEvidence !== item.id) { setSelectedEvidence(item.id); setCustody(null); }
          }}><strong>{item.name}</strong><small>{item.classification} · {item.archived ? "archived" : `${item.sequence} custody events`}</small></button>)}</div>
          {writable && <details className="detection-history"><summary>Register stored evidence</summary>
            <form className="detection-form" onSubmit={event => {
              event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
              const id = String(data.get("evidence_id") || "").trim();
              void act(async () => {
                await saveAction("evidence", { evidence_id: id, classification: data.get("classification"), purpose: data.get("purpose"), tags: String(data.get("tags") || "").split(",").map(value => value.trim()).filter(Boolean) });
                setSelectedEvidence(id); form.reset();
              });
            }}>
              <label>Evidence ID<input name="evidence_id" maxLength={120} required/></label>
              <label>Classification<select name="classification"><Options items={["document", "log", "image", "archive", "other"]}/></select></label>
              <label>Tags (comma separated)<input name="tags" maxLength={300}/></label>
              <label>Purpose<input name="purpose" minLength={3} maxLength={500} required/></label>
              <button className="agents-refresh" disabled={busy}>Register evidence</button>
            </form>
          </details>}
          {activeEvidence && <>
            <h3>{activeEvidence.name}</h3><small>{activeEvidence.original_filename || "Original filename unavailable"} · {activeEvidence.signature || "Unknown signature"} · {activeEvidence.size_bytes ?? "Unknown size"}</small>
            <p>Custodian {staff.find(item => item.id === activeEvidence.custodian_id)?.name || activeEvidence.custodian_id || "Unassigned"}</p>
            {!!activeEvidence.tags.length && <p>Tags {activeEvidence.tags.join(", ")}</p>}
            <div className="intake-evidence"><small>SHA-256 {activeEvidence.sha256}</small><small>SHA-512 {activeEvidence.sha512}</small></div>
            <EvidenceImageMetadata metadata={activeEvidence.image_metadata} />
            {custody && <p role="status">Custody chain {custody.chain_status}</p>}
            {!custody && !error && <p role="status">Loading custody history…</p>}
            {isWriter && !activeEvidence.archived && custody?.chain_status === "valid" && <form key={`${activeEvidence.id}-${activeEvidence.sequence}`} className="detection-form" onSubmit={event => {
              event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
              const action = String(data.get("action")); const purpose = String(data.get("purpose")).trim();
              void act(async () => {
                if (action === "export") await exportEvidence(purpose);
                else await saveAction(`evidence/${activeEvidence.id}/custody`, { action, purpose, custodian_id: action === "transfer" ? data.get("custodian_id") || null : null, expected_sequence: activeEvidence.sequence });
                form.reset();
              });
            }}>
              <label>Action<select name="action"><Options items={writable ? ["verify", "transfer", "examine", "export", "archive"] : ["export"]}/></select></label>
              {writable && <label>New custodian for transfers<select name="custodian_id"><option value="">Select investigator</option>{staff.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
              <label>Purpose<input name="purpose" minLength={3} maxLength={500} required/></label>
              <button className="agents-refresh" disabled={busy}>Record custody action</button>
            </form>}
            {custody && <ol className="detection-sources">{[...custody.events].reverse().map(item => <li key={item.sequence}><strong>#{item.sequence} · {item.action.replaceAll("_", " ")}</strong><p>{item.purpose}</p>
              <time dateTime={item.time}>{localTime(item.time)}</time><small>{item.previous_custodian_id || "Unassigned"} → {item.new_custodian_id || "Unassigned"}</small><small>Entry SHA-256 {item.integrity_hash}</small></li>)}</ol>}
          </>}
        </>}
      </aside>
    </div>
  </main>;
}
