"use client";

import { useEffect, useState } from "react";
import { type Availability, workspace } from "@/lib/ai-workspace";
import { forensic, forensicBody } from "@/lib/forensic";

type Interpretation = { id: string; status: string; error: string | null; review_status: string; review_note: string | null;
  result: { answer: string; citations: string[] } | null;
  usage: { provider: string; model: string; input_tokens: number | null; output_tokens: number | null; duration_ms: number | null } | null };

export default function NexusInterpretations({ runId, taskId, canReview }: { runId: string; taskId: string; canReview: boolean }) {
  const path = `investigations/${runId}/tasks/${taskId}/interpretations`;
  const [rows, setRows] = useState<Interpretation[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([forensic<Interpretation[]>(path, { signal: controller.signal }),
      workspace<Availability>("ai/availability", { signal: controller.signal })])
      .then(([history, settings]) => { setRows(history); setEnabled(settings.available && settings.mode === "hybrid"); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [path]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); setRows(await forensic<Interpretation[]>(path)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Interpretation request failed."); }
    finally { setBusy(false); }
  }

  return <details className="detection-history">
    <summary>Model interpretations</summary>
    {error && <p role="alert">{error}</p>}
    {!enabled && <p>Hybrid model assistance is unavailable under the current AI settings.</p>}
    {enabled && <form className="detection-form" onSubmit={event => {
      event.preventDefault();
      void act(async () => {
        const requestKey = key || crypto.randomUUID(); setKey(requestKey);
        await forensic(path, forensicBody("POST", { request_key: requestKey, acknowledge_model_context: consent }));
        setConsent(false); setKey("");
      });
    }}><label className="ai-check"><input type="checkbox" checked={consent} required onChange={event => setConsent(event.target.checked)}/>
      Send this saved finding summary and source identifiers to the configured model</label>
      <button className="agents-refresh" disabled={busy || !consent}>{busy ? "Working…" : "Interpret finding"}</button>
    </form>}
    <ol className="detection-sources">{rows.map(item => <li key={item.id}>
      <strong>{item.status} · Review {item.review_status}</strong>
      {item.usage && <small>{item.usage.provider} · {item.usage.model} · {item.usage.input_tokens ?? "—"} input / {item.usage.output_tokens ?? "—"} output tokens</small>}
      {item.result && <><p className="ai-wrap">{item.result.answer}</p><small>Source {item.result.citations.join(", ")}</small></>}
      {item.error && <p role="alert">{item.error}</p>}
      {item.review_note && <p>{item.review_note}</p>}
      {canReview && item.result && item.review_status === "pending" && <form className="detection-form" onSubmit={event => {
        event.preventDefault(); const values = new FormData(event.currentTarget);
        void act(async () => { await forensic(`${path}/${item.id}/review`, forensicBody("POST", { decision: values.get("decision"), note: values.get("note") })); });
      }}><label>Review decision<select name="decision"><option value="approved">Approve interpretation</option><option value="rejected">Reject interpretation</option></select></label>
        <label>Review note<input name="note" minLength={3} maxLength={500} required/></label>
        <button className="agents-refresh" disabled={busy}>Save interpretation review</button>
      </form>}
    </li>)}</ol>
  </details>;
}
