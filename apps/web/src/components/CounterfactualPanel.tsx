"use client";

import { useEffect, useState } from "react";
import { displayDate, intake, jsonRequest } from "@/lib/intake";

type Event = { id: string; title: string };
type Policy = { window_minutes: number; refund_threshold: number; failure_threshold: number };
type Assessment = { score: number; refund_ids: string[]; security_event_ids: string[] };
type Scenario = { id: string; created_at: string; assumptions: { scenario: string; event_id: string | null; policy: Policy | null };
  original: Assessment; current_baseline: Assessment; adjusted: Assessment;
  added_factors: string[]; removed_factors: string[]; remaining_factors: string[]; uncertainty: string[] };
const scenarios = {
  exclude_device: "Exclude the reported refund device link",
  legitimate_refund: "Treat the refund as legitimate",
  exclude_event: "Exclude a disputed security event",
  adjust_thresholds: "Change the correlation thresholds",
};
type Kind = keyof typeof scenarios;

export default function CounterfactualPanel({ findingId, events, policy }: { findingId: string; events: Event[]; policy: Policy }) {
  const path = `commerce/findings/${findingId}/scenarios`;
  const [kind, setKind] = useState<Kind>("exclude_device");
  const [saved, setSaved] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = saved.find(item => item.id === selected);

  useEffect(() => {
    const controller = new AbortController();
    void intake<Scenario[]>(path, { signal: controller.signal }).then(rows => {
      if (!controller.signal.aborted) { setSaved(rows); setSelected(rows[0]?.id || ""); }
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [path]);

  return <details className="detection-history">
    <summary>Counterfactual scenarios</summary>
    {error && <p role="alert">{error}</p>}
    <form className="detection-form" onSubmit={event => {
      event.preventDefault(); const fields = new FormData(event.currentTarget);
      setBusy(true); setError("");
      const changed = kind === "adjust_thresholds" ? Object.fromEntries(
        Object.keys(policy).map(key => [key, Number(fields.get(key))]),
      ) : undefined;
      void intake<Scenario>(path, jsonRequest("POST", { scenario: kind,
        event_id: kind === "exclude_event" ? fields.get("event") : undefined, policy: changed,
      })).then(item => { setSaved(current => [item, ...current].slice(0, 20)); setSelected(item.id); })
        .catch(cause => setError(cause.message)).finally(() => setBusy(false));
    }}>
      <label>Hypothetical change<select value={kind} onChange={event => setKind(event.target.value as Kind)}>
        {Object.entries(scenarios).map(([value, label]) => <option key={value} value={value} disabled={value === "exclude_event" && !events.length}>{label}</option>)}
      </select></label>
      {kind === "exclude_event" && <label>Disputed security event<select name="event" required><option value="">Select a linked event</option>
        {events.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>}
      {kind === "adjust_thresholds" && <>
        <label>Window in minutes<input name="window_minutes" type="number" min={5} max={1440} required defaultValue={policy.window_minutes}/></label>
        <label>Refund threshold<input name="refund_threshold" type="number" min={2} max={20} required defaultValue={policy.refund_threshold}/></label>
        <label>Failed sign-in threshold<input name="failure_threshold" type="number" min={2} max={20} required defaultValue={policy.failure_threshold}/></label>
      </>}
      <button className="agents-refresh" disabled={busy}>{busy ? "Evaluating…" : "Evaluate scenario"}</button>
    </form>
    {!!saved.length && <label className="detection-form">Saved scenario<select value={selected} onChange={event => setSelected(event.target.value)}>
      {saved.map(row => <option key={row.id} value={row.id}>{scenarios[row.assumptions.scenario as Kind]} · {displayDate(row.created_at)}</option>)}</select></label>}
    {active && <section aria-label="Hypothetical comparison"><h3>Hypothetical comparison</h3>
      <p>Stored finding {active.original.score}/100 · Recomputed baseline {active.current_baseline.score}/100 · Scenario {active.adjusted.score}/100</p>
      <ul className="detection-sources">
        <li>Removed factors {active.removed_factors.map(item => item.replaceAll("_", " ")).join(", ") || "None"}</li>
        <li>Added factors {active.added_factors.map(item => item.replaceAll("_", " ")).join(", ") || "None"}</li>
        <li>Remaining factors {active.remaining_factors.map(item => item.replaceAll("_", " ")).join(", ") || "None"}</li>
      </ul>
      <p>{active.adjusted.refund_ids.length} refund records and {active.adjusted.security_event_ids.length} security events support the adjusted assessment.</p>
      {active.uncertainty.map(item => <p key={item}>{item}</p>)}
    </section>}
  </details>;
}
