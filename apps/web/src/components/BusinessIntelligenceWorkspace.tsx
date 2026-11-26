"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { workspace } from "@/lib/ai-workspace";

type Summary = { currency: string; payments: number; refunds: number; paid_minor: string; refunded_minor: string };
type CurrencySummary = Summary & { net_recorded_minor: string; average_payment_minor: string | null;
  refund_count_per_100_payments: string | null; refund_amount_per_100_paid: string | null; previous: Summary };
type Day = Summary & { date: string };
type Report = { period: { start: string; end: string }; comparison: { start: string; end: string };
  summary: CurrencySummary[]; days: Day[]; segments: { currency: string; segment: string; reported_accounts: number }[];
  finding_statuses: { currency: string; status: string; count: number }[]; limitations: string[] };
const base = "business-intelligence";
const numbers = { one_record: "1 record", two_to_four: "2–4 records", five_or_more: "5 or more records" };
const formatMinor = (text: string) => BigInt(text).toLocaleString();

export default function BusinessIntelligenceWorkspace() {
  const [report, setReport] = useState<Report>();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [currency, setCurrency] = useState("");
  const [selection, setSelection] = useState("");
  const [day, setDay] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const view = report?.summary.find(item => item.currency === selection) || report?.summary[0];
  const days = report?.days.filter(item => item.currency === view?.currency) || [];
  const inspected = days.find(item => item.date === day);
  const maximum = days.reduce((scale, item) => {
    const highest = BigInt(item.paid_minor) > BigInt(item.refunded_minor) ? BigInt(item.paid_minor) : BigInt(item.refunded_minor);
    return highest > scale ? highest : scale;
  }, BigInt(1));

  async function load(from = "", to = "", code = "") {
    setLoading(true); setError("");
    try {
      const query = new URLSearchParams();
      if (from) query.set("start", from);
      if (to) query.set("end", to);
      if (code) query.set("currency", code);
      const result = await workspace<Report>(`${base}/report?${query}`);
      setReport(result); setStart(result.period.start); setEnd(result.period.end); setDay("");
      setSelection(current => result.summary.some(item => item.currency === current) ? current : result.summary[0]?.currency || "");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Business report unavailable."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  const exportQuery = report ? new URLSearchParams({ start: report.period.start, end: report.period.end }) : new URLSearchParams();
  if (view) exportQuery.set("currency", view.currency);
  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Business Intelligence</h1><p>Compare recorded payments, refunds, and commerce findings in their original currencies.</p></div>
      <Link className="agents-refresh" href="/platform/fraud">Fraud intelligence</Link></header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    <form className="panel intake-panel business-filters" onSubmit={event => { event.preventDefault(); void load(start, end, currency.trim().toUpperCase()); }}>
      <label>UTC start<input type="date" value={start} onChange={event => setStart(event.target.value)} required/></label>
      <label>UTC end<input type="date" value={end} onChange={event => setEnd(event.target.value)} required/></label>
      <label>Currency filter<input value={currency} maxLength={3} pattern="[A-Za-z]{3}" placeholder="All" onChange={event => setCurrency(event.target.value)}/></label>
      <button className="primary-button" disabled={loading || !start || !end}>Apply filters</button>
    </form>
    {loading && <p role="status">Loading records…</p>}
    {report && !report.summary.length && <p>No recorded payments or refunds were found for either period.</p>}
    {report && view && <>
      <div className="intake-actions business-toolbar">
        <label>Report currency <select value={view.currency} onChange={event => { setSelection(event.target.value); setDay(""); }}>
          {report.summary.map(item => <option key={item.currency}>{item.currency}</option>)}</select></label>
        <a className="agents-refresh" href={`/api/workspace/${base}/export?${exportQuery}&format=csv`}>Export CSV</a>
        <a className="agents-refresh" href={`/api/workspace/${base}/export?${exportQuery}&format=json`}>Export JSON</a>
      </div>
      <section className="intake-totals" aria-label="Executive summary">
        {[["Recorded payments", view.paid_minor, view.previous.paid_minor], ["Recorded refunds", view.refunded_minor, view.previous.refunded_minor],
          ["Net recorded amount", view.net_recorded_minor, String(BigInt(view.previous.paid_minor) - BigInt(view.previous.refunded_minor))]].map(([label, value, previous]) =>
          <article className="panel" key={label}><small>{label}</small><strong>{formatMinor(value)}</strong>
            <small>{view.currency} minor units · Previous {formatMinor(previous)}</small></article>)}
        <article className="panel"><small>Refund records per 100 payments</small><strong>{view.refund_count_per_100_payments ?? "—"}</strong>
          <small>{view.refunds} refunds · {view.payments} payments</small></article>
      </section>
      <div className="ai-settings-grid">
        <section className="panel intake-panel"><h2>Daily activity</h2>
          <p>{report.period.start} to {report.period.end} UTC. Comparison {report.comparison.start} to {report.comparison.end}.</p>
          {!days.length && <p>No records for this currency in the current period.</p>}
          {!!days.length && <div className="business-chart" role="group" aria-label="Daily payment and refund amounts">
            {days.map(item => <button type="button" key={item.date} aria-pressed={day === item.date} className="business-bars"
              onClick={() => setDay(item.date)} onFocus={() => setDay(item.date)}
              title={`${item.date} · Paid ${formatMinor(item.paid_minor)} · Refunded ${formatMinor(item.refunded_minor)}`}
              aria-label={`${item.date}, ${item.payments} payments, ${item.refunds} refunds`}>
              <span style={{ height: `${Number(BigInt(item.paid_minor) * BigInt(100) / maximum)}%` }}/>
              <span style={{ height: `${Number(BigInt(item.refunded_minor) * BigInt(100) / maximum)}%` }}/>
            </button>)}
          </div>}
          {inspected && <p role="status">{inspected.date} · {formatMinor(inspected.paid_minor)} paid · {formatMinor(inspected.refunded_minor)} refunded</p>}
          <div className="table-wrap"><table className="incident-table">
            <thead><tr><th>UTC day</th><th>Payments</th><th>Refunds</th><th>Paid minor units</th><th>Refunded minor units</th></tr></thead>
            <tbody>{(inspected ? [inspected] : days.slice(-14).reverse()).map(item => <tr key={item.date}>
              <td>{item.date}</td><td>{item.payments}</td><td>{item.refunds}</td><td>{formatMinor(item.paid_minor)}</td><td>{formatMinor(item.refunded_minor)}</td></tr>)}</tbody>
          </table></div>
          {inspected && <button className="agents-refresh" onClick={() => setDay("")}>Show recent days</button>}
        </section>
        <section className="panel intake-panel"><h2>Recorded commerce indicators</h2>
          <dl className="business-metrics"><dt>Average payment in minor units</dt><dd>{view.average_payment_minor ?? "Unavailable"}</dd>
            <dt>Refund amount per 100 paid</dt><dd>{view.refund_amount_per_100_paid ?? "Unavailable"}</dd></dl>
          <h3>Reported account activity</h3>
          <ul className="detection-sources">{report.segments.filter(item => item.currency === view.currency).map(item =>
            <li key={item.segment}><strong>{item.reported_accounts}</strong><small>{numbers[item.segment as keyof typeof numbers]}</small></li>)}</ul>
          <h3>Refund finding status</h3>
          {!report.finding_statuses.some(item => item.currency === view.currency) && <p>No findings in the selected currency and period.</p>}
          <ul className="detection-sources">{report.finding_statuses.filter(item => item.currency === view.currency).map(item =>
            <li key={item.status}><strong>{item.count}</strong><small>{item.status}</small></li>)}</ul>
          <details className="detection-history"><summary>Calculation notes</summary>
            <ul>{report.limitations.map(line => <li key={line}>{line}</li>)}</ul></details>
        </section>
      </div>
    </>}
  </main>;
}
