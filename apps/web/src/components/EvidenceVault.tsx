"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Download, FileCheck2, FileUp, Fingerprint, RefreshCw } from "lucide-react";
import { displayDate, intake } from "@/lib/intake";
import EvidenceImageMetadata, { type ImageMetadata } from "@/components/EvidenceImageMetadata";

type Evidence = { id: string; name: string; sha256: string; sha512: string; mime_type: string; investigation_id: string | null; immutable: boolean; created_at: string; custody_registered: boolean; forensic_case_id: string | null; image_metadata: ImageMetadata | null };
type Activity = { action: string; time: string; result: string | null };
type Verification = { integrity: "match" | "mismatch"; signature: string | null; size_bytes: number; image_metadata: ImageMetadata | null };

export default function EvidenceVault() {
  const [items, setItems] = useState<Evidence[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [incidentId, setIncidentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [inspectedId, setInspectedId] = useState("");
  const [activity, setActivity] = useState<Activity[] | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [canVerify, setCanVerify] = useState(false);
  const inspected = items.find(item => item.id === inspectedId);

  const load = useCallback(async () => {
    setError("");
    try {
      const response = await fetch("/api/evidence", { cache: "no-store" });
      if (response.status === 401) { window.location.assign("/login"); return; }
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Evidence records are unavailable.");
      setItems(body);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Evidence service is unavailable."); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/session", { signal: controller.signal, cache: "no-store" }).then(async response => {
      if (!response.ok) return;
      const identity = await response.json();
      if (!controller.signal.aborted) setCanVerify(["owner", "organization_admin", "security_analyst", "forensic_investigator"].includes(identity.user.role));
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!inspectedId) return;
    const controller = new AbortController();
    intake<Activity[]>(`evidence/${inspectedId}/activity`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setActivity(result); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [inspectedId]);

  function inspect(item: Evidence) {
    if (inspectedId === item.id) return;
    setInspectedId(item.id); setActivity(null); setVerification(null); setError("");
  }

  async function verify() {
    if (!inspected) return;
    setBusy(true); setError(""); setVerification(null);
    try {
      const result = await intake<Verification>(`evidence/${inspected.id}/verify`, { method: "POST" });
      setVerification(result);
      if (result.image_metadata) setItems(current => current.map(item =>
        item.id === inspected.id ? { ...item, image_metadata: result.image_metadata } : item));
      setActivity(await intake<Activity[]>(`evidence/${inspected.id}/activity`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Evidence verification failed.");
    } finally {
      setBusy(false);
    }
  }

  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setError("Choose a file before uploading."); return; }
    setBusy(true); setError(""); setMessage("");
    const form = new FormData(); form.set("file", file); form.set("name", name.trim() || file.name);
    if (incidentId.trim()) form.set("investigation_id", incidentId.trim());
    try {
      const response = await fetch("/api/evidence", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Evidence upload failed.");
      setMessage(`Stored ${body.name}; integrity digests were recorded.`);
      setFile(null); setName(""); setIncidentId("");
      const input = document.getElementById("evidence-file") as HTMLInputElement | null;
      if (input) input.value = "";
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Evidence upload failed."); }
    finally { setBusy(false); }
  }

  return <main className="evidence-page">
    <header className="evidence-header"><div><div className="agents-kicker">INVESTIGATION / EVIDENCE</div><h1>Evidence vault</h1><p>Tenant-protected files with recorded SHA-256 and SHA-512 integrity checks.</p></div><button className="agents-refresh" onClick={() => void load()}><RefreshCw size={14}/> Refresh</button></header>
    <div className="evidence-notice"><Fingerprint size={17}/><span>Downloads check both stored digests. Register a file in <Link href="/platform/forensics">Forensic cases</Link> to record custody and export activity.</span></div>
    {error && <div className="agents-error" role="alert">{error}</div>}{message && <div className="agents-success" role="status">{message}</div>}
    <section className="panel evidence-upload"><div><div className="agents-kicker">ADD RECORD</div><h2>Upload evidence</h2><p>Maximum file size: 25 MiB. Evidence is associated with your current organization.</p></div><form onSubmit={(event) => void upload(event)}><label htmlFor="evidence-file">Evidence file</label><input id="evidence-file" type="file" required onChange={(event) => setFile(event.target.files?.[0] || null)}/><label htmlFor="evidence-name">Record name</label><input id="evidence-name" value={name} onChange={(event) => setName(event.target.value)} placeholder={file?.name || "Optional display name"}/><label htmlFor="evidence-incident">Incident ID (optional)</label><input id="evidence-incident" value={incidentId} onChange={(event) => setIncidentId(event.target.value)} placeholder="Attach to an incident"/><button className="agents-run-button" disabled={busy || !file}><FileUp size={15}/>{busy ? "Saving evidence…" : "Upload and verify"}</button></form></section>
    <section className="agent-history"><div className="agent-history-title"><div><div className="agents-kicker">AUTHORIZED RECORDS</div><h2>Evidence inventory</h2></div><span>{items.length} records</span></div>{items.length ? items.map(item => <article className="evidence-row" key={item.id}><div className="evidence-icon"><FileCheck2 size={17}/></div><div className="evidence-meta"><strong>{item.name}</strong><small>{item.mime_type} · {new Date(item.created_at).toLocaleString()}</small><code>{item.id}</code></div><button className="agents-refresh" type="button" disabled={busy} onClick={() => inspect(item)}>Inspect</button>{item.forensic_case_id && <Link className="agents-refresh evidence-download" href={`/platform/forensics?case=${encodeURIComponent(item.forensic_case_id)}`}>Open case</Link>}{!item.custody_registered && <a className="agents-refresh evidence-download" href={`/api/evidence/${encodeURIComponent(item.id)}/download`}><Download size={14}/> Download</a>}</article>) : <div className="agent-empty">No evidence files are stored for this organization.</div>}</section>
    {inspected && <section className="panel intake-panel" aria-label="Evidence inspector">
      <h2>{inspected.name}</h2>
      <div className="intake-evidence"><small>SHA-256 {inspected.sha256}</small><small>SHA-512 {inspected.sha512}</small></div>
      {canVerify && <EvidenceImageMetadata metadata={inspected.image_metadata} />}
      {canVerify && !inspected.custody_registered && <button type="button" className="primary-button" disabled={busy} onClick={() => void verify()}>Verify stored bytes</button>}
      {verification && <p role="status">{verification.integrity === "match" ? "Both hashes match." : "Hash mismatch. Treat the file as altered."} {verification.size_bytes} bytes · {verification.signature || "No recognized signature"}</p>}
      <h3>Audit activity</h3>
      {activity === null && !error && <p role="status">Loading activity…</p>}
      {activity?.length === 0 && <p>No upload or verification activity was recorded for this evidence.</p>}
      {activity && <ul className="detection-sources">{activity.map((item, index) => <li key={`${item.time}-${index}`}><strong>{item.action === "evidence.upload" ? "Uploaded" : `Integrity check · ${item.result}`}</strong><time dateTime={item.time}>{displayDate(item.time)}</time></li>)}</ul>}
    </section>}
  </main>;
}
