"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { displayDate, intake, jsonRequest } from "@/lib/intake";
import CounterfactualPanel from "@/components/CounterfactualPanel";

type Transaction = {
  id: string; external_id: string; kind: "payment" | "refund"; account: string;
  currency: string; amount_minor: number; occurred_at: string;
};
type Totals = { currency: string; kind: string; count: number; amount_minor: string };
type Policy = { window_minutes: number; refund_threshold: number; failure_threshold: number };
type Finding = {
  id: string; status: "open" | "confirmed" | "dismissed"; score: number; refund: Transaction;
  factors: { code: string; weight: number; detail: string }[]; limitations: string;
  alternative_explanations: string[]; incident_id: string | null; graph_entity_id: string | null;
  policy: Policy;
};
type Sources = {
  refunds: Transaction[];
  security_events: { id: string; title: string; occurred_at: string; source_reference: string }[];
  evidence: { id: string; name: string; sha256: string }[];
};

export default function FraudWorkspace() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [totals, setTotals] = useState<Totals[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [selected, setSelected] = useState("");
  const [sources, setSources] = useState<Sources | null>(null);
  const [note, setNote] = useState("");
  const [role, setRole] = useState("");
  const [filter, setFilter] = useState("open");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const active = findings.find(item => item.id === selected);
  const canReview = ["owner", "organization_admin", "security_analyst", "business_analyst"].includes(role);
  const canConfigure = ["owner", "organization_admin"].includes(role);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const request = { signal };
    const [sales, records, amounts, currentPolicy] = await Promise.all([
      intake<Transaction[]>("commerce/records", request), intake<Finding[]>("commerce/findings", request),
      intake<Totals[]>("commerce/totals", request), intake<Policy>("commerce/policy", request),
    ]);
    if (signal?.aborted) return;
    setTransactions(sales); setFindings(records); setTotals(amounts); setPolicy(currentPolicy);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const finding = new URLSearchParams(window.location.search).get("finding");
    if (finding) { setSelected(finding); setFilter("all"); }
    void Promise.all([refresh(controller.signal), fetch("/api/auth/session", { signal: controller.signal })
      .then(async response => {
        if (!response.ok) return;
        const identity = await response.json();
        if (!controller.signal.aborted) setRole(identity.user.role);
      })]).catch(cause => { if (!controller.signal.aborted) setError(cause.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    void intake<Sources>(`commerce/findings/${selected}/sources`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setSources(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected]);

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Fraud workspace request failed.");
    } finally { setBusy(false); }
  }

  function selectFinding(id: string) {
    if (selected === id) return;
    setSelected(id); setSources(null); setNote("");
  }

  async function resolve(action: "incident" | "dismiss") {
    if (!active) return;
    await intake(`commerce/findings/${active.id}/${action}`,
      action === "dismiss" ? jsonRequest("POST", { note: note.trim() }) : { method: "POST" });
    setNotice(action === "incident" ? "Incident created with supporting records." : "Review feedback saved.");
    await refresh();
  }

  function exportReport() {
    if (!active || !sources) return;
    const blob = new Blob([JSON.stringify({ finding: active, sources }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = `finding-${active.id}.json`;
    download.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const visible = findings.filter(item => (filter === "all" || item.status === filter)
    && `${item.refund.account} ${item.refund.external_id}`.toLowerCase().includes(query.toLowerCase()));
  const timeline = sources ? [
    ...sources.refunds.map(row => ({ id: row.id, label: `Refund ${row.external_id} · ${row.currency} ${row.amount_minor} minor units`, at: row.occurred_at })),
    ...sources.security_events.map(row => ({ id: row.id, label: `${row.title} · ${row.source_reference || row.id}`, at: row.occurred_at })),
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)) : [];

  return <main className="intake-page">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Fraud intelligence</h1><p>Review refund activity alongside recorded authentication observations.</p></div>
      <div className="intake-actions"><Link className="agents-refresh" href="/platform/data-sources">Data sources</Link><button className="agents-refresh" disabled={busy || loading} onClick={() => void run(() => refresh())}>Refresh</button></div></header>
    {loading && <p role="status">Loading fraud records…</p>}
    {error && <p className="agents-error" role="alert">{error}</p>}
    {notice && <p className="agents-success" role="status">{notice}</p>}
    {!!totals.length && <section className="intake-totals" aria-label="Recorded totals by currency">
      {totals.map(item => <article className="panel" key={`${item.currency}-${item.kind}`}><small>{item.currency} · {item.kind}</small>
        <strong>{item.amount_minor} minor units</strong><small>{item.count} recorded</small></article>)}
    </section>}
    <div className="intake-layout fraud-layout">
      <section className="panel intake-panel">
        <h2>Review queue</h2>
        <div className="detection-form"><label>Search account or refund<input value={query} onChange={event => setQuery(event.target.value)}/></label>
          <label>Review status<select value={filter} onChange={event => setFilter(event.target.value)}>
            <option value="open">Open</option><option value="confirmed">Confirmed</option><option value="dismissed">Dismissed</option><option value="all">All</option>
          </select></label></div>
        <div className="intake-list">{visible.map(item => <button type="button" key={item.id} aria-pressed={selected === item.id} onClick={() => selectFinding(item.id)} disabled={busy}>
          <strong>{item.refund.external_id} · {item.refund.account}</strong><small>{item.score}/100 rule score · {item.status}</small>
        </button>)}</div>
        {!loading && !visible.length && !error && <p>No findings match these filters.</p>}
        {canConfigure && policy && <details className="detection-history"><summary>Correlation settings</summary>
          <form className="detection-form" onSubmit={event => { event.preventDefault(); void run(async () => {
            await intake("commerce/policy", jsonRequest("PUT", policy)); setNotice("Settings saved for future evaluations.");
          }); }}>
            <label>Look-back (minutes)<input required type="number" min={5} max={1440} value={policy.window_minutes || ""} onChange={event => setPolicy({ ...policy, window_minutes: Number(event.target.value) })}/></label>
            <label>Refund threshold<input required type="number" min={2} max={20} value={policy.refund_threshold || ""} onChange={event => setPolicy({ ...policy, refund_threshold: Number(event.target.value) })}/></label>
            <label>Failed sign-in threshold<input required type="number" min={2} max={20} value={policy.failure_threshold || ""} onChange={event => setPolicy({ ...policy, failure_threshold: Number(event.target.value) })}/></label>
            <button className="agents-refresh" disabled={busy}>Save settings</button>
          </form>
        </details>}
      </section>
      <section className="panel intake-panel" aria-label="Finding inspector">
        <h2>Finding and timeline</h2>
        {!active && <p>Select a finding to inspect the report.</p>}
        {active && <>
          <h3>{active.refund.external_id} · {active.score}/100 rule score</h3>
          <p>{active.limitations}</p>
          <p>{active.policy.window_minutes}-minute correlation window.</p>
          <ul className="detection-sources">{active.factors.map(factor => <li key={factor.code}><strong>+{factor.weight} · {factor.code.replaceAll("_", " ")}</strong><small>{factor.detail}</small></li>)}</ul>
          <details className="detection-history"><summary>Alternative explanations</summary><ul>{active.alternative_explanations.map(item => <li key={item}>{item}</li>)}</ul></details>
          {canReview && <CounterfactualPanel key={active.id} findingId={active.id} events={sources?.security_events || []} policy={active.policy} />}
          {!sources && !error && <p role="status">Loading supporting records…</p>}
          {!!timeline.length && <ol className="detection-sources">{timeline.map(row => <li key={row.id}>
            <time dateTime={row.at}>{displayDate(row.at)}</time><strong>{row.label}</strong>
          </li>)}</ol>}
          {sources?.evidence.map(item => <div className="intake-evidence" key={item.id}><Link href={`/api/evidence/${item.id}/download`}>{item.name}</Link><small>SHA-256 {item.sha256}</small></div>)}
          <div className="intake-actions">
            {sources && <button className="agents-refresh" onClick={exportReport}>Export report JSON</button>}
            {active.incident_id && <Link className="agents-refresh" href={`/platform/incidents?id=${active.incident_id}`}>Open incident</Link>}
            {active.graph_entity_id && <Link className="agents-refresh" href={`/platform/graph?focus=${active.graph_entity_id}`}>Explore graph</Link>}
          </div>
          {canReview && active.status === "open" && <div className="detection-form">
            <button className="primary-button" disabled={busy || !active.score || !sources} onClick={() => void run(() => resolve("incident"))}>Confirm and create incident</button>
            <label>Dismissal reason<textarea value={note} maxLength={1000} onChange={event => setNote(event.target.value)} rows={2}/></label>
            <button className="agents-refresh" disabled={busy || note.trim().length < 3} onClick={() => void run(() => resolve("dismiss"))}>Dismiss finding</button>
          </div>}
        </>}
      </section>
      <section className="panel intake-panel" aria-label="Recent commerce records">
        <h2>Recent records</h2>
        {!loading && !transactions.length && !error && <p>Submit payments or refunds in Data Sources.</p>}
        <ul className="detection-sources">{transactions.map(row => <li key={row.id}>
          <strong>{row.external_id} · {row.kind}</strong><small>{row.account} · {row.currency} {row.amount_minor} minor units</small><time dateTime={row.occurred_at}>{displayDate(row.occurred_at)}</time>
          {canReview && row.kind === "refund" && <button className="agents-refresh" disabled={busy} onClick={() => void run(async () => {
            const result = await intake<{ id: string } | null>(`commerce/refunds/${row.id}/evaluate`, { method: "POST" });
            await refresh();
            if (result?.id === selected) setSources(await intake<Sources>(`commerce/findings/${result.id}/sources`));
            else if (result) selectFinding(result.id);
            setNotice(result ? "Refund evaluated against available records." : "No risk factors matched the current records.");
          })}>Evaluate refund</button>}
        </li>)}</ul>
      </section>
    </div>
  </main>;
}
