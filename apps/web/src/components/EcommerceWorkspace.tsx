"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Download, RefreshCw, ShoppingCart } from "lucide-react";
import { workspace } from "@/lib/ai-workspace";

type Transaction = {
  id: string;
  external_id: string;
  kind: "payment" | "refund";
  account: string;
  device: string | null;
  order_reference: string | null;
  currency: string;
  amount_minor: number;
  evidence_id: string | null;
  occurred_at: string;
};

type TransactionPage = { items: Transaction[]; total: number; limit: number; offset: number };
type Total = { currency: string; kind: string; count: number; amount_minor: string };
type Finding = { id: string; refund_id: string; score: number; status: string; factors?: unknown[] };

export default function EcommerceWorkspace() {
  const [page, setPage] = useState<TransactionPage>({ items: [], total: 0, limit: 100, offset: 0 });
  const [totals, setTotals] = useState<Total[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selected, setSelected] = useState<(Transaction & { finding: Finding | null; evidence: unknown; security_events: unknown[] }) | null>(null);
  const [kind, setKind] = useState("");
  const [currency, setCurrency] = useState("");
  const [account, setAccount] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (kind) params.set("kind", kind);
      if (currency) params.set("currency", currency.toUpperCase());
      if (account) params.set("account", account);
      if (search) params.set("search", search);
      const [transactions, amounts, commerceFindings] = await Promise.all([
        workspace<TransactionPage>(`commerce/transactions?${params}`),
        workspace<Total[]>("commerce/totals"),
        workspace<Finding[]>("commerce/findings"),
      ]);
      setPage(transactions);
      setTotals(amounts);
      setFindings(commerceFindings);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "E-commerce records are unavailable.");
    } finally {
      setLoading(false);
    }
  }, [kind, currency, account, search]);

  useEffect(() => { void load(); }, [load]);

  const currencies = useMemo(() => [...new Set(totals.map((row) => row.currency))].sort(), [totals]);
  const selectedCurrency = currency ? currency.toUpperCase() : currencies[0] || "";
  const payment = totals.find((row) => row.currency === selectedCurrency && row.kind === "payment");
  const refund = totals.find((row) => row.currency === selectedCurrency && row.kind === "refund");
  const paymentCount = payment?.count || 0;
  const refundCount = refund?.count || 0;
  const paid = BigInt(payment?.amount_minor || "0");
  const refunded = BigInt(refund?.amount_minor || "0");
  const refundRate = paymentCount ? `${((refundCount / paymentCount) * 100).toFixed(1)} per 100` : "Unavailable";

  const inspect = async (id: string) => {
    setError("");
    try {
      setSelected(await workspace<(Transaction & { finding: Finding | null; evidence: unknown; security_events: unknown[] })>(`commerce/records/${id}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Transaction details are unavailable.");
    }
  };

  const exportQuery = new URLSearchParams();
  if (kind) exportQuery.set("kind", kind);
  if (selectedCurrency) exportQuery.set("currency", selectedCurrency);

  return <main className="module-page commerce-page">
    <header className="module-heading"><div><div className="eyebrow">MERCHANT INTELLIGENCE</div><h1>E-commerce analytics</h1><p>Recorded payments, refunds, accounts, and fraud relationships in source currencies.</p></div><div className="module-actions"><button className="outline-button" type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} className={loading ? "spin" : ""}/>Refresh</button><a className="primary-button" href={`/api/workspace/commerce/export?${exportQuery}&format=csv`}><Download size={15}/>Export CSV</a></div></header>
    {error && <div className="notice" role="alert"><AlertTriangle size={16}/><div><strong>Commerce request failed</strong><span>{error}</span></div></div>}
    <form className="panel commerce-filters" onSubmit={(event) => { event.preventDefault(); void load(); }}>
      <label>Transaction<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="">All records</option><option value="payment">Payments</option><option value="refund">Refunds</option></select></label>
      <label>Currency<select value={currency} onChange={(event) => setCurrency(event.target.value)}><option value="">All currencies</option>{currencies.map((code) => <option key={code}>{code}</option>)}</select></label>
      <label>Account<input value={account} onChange={(event) => setAccount(event.target.value)} placeholder="Reported account"/></label>
      <label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Transaction or order reference"/></label>
      <button className="primary-button" type="submit" disabled={loading}>Apply</button>
    </form>
    <section className="module-stat-grid commerce-metrics">
      {[["Recorded payments", String(paymentCount), selectedCurrency || "No currency"], ["Recorded refunds", String(refundCount), selectedCurrency || "No currency"], ["Net recorded amount", (paid - refunded).toLocaleString(), `${selectedCurrency || "No currency"} minor units`], ["Refund record share", refundRate, "Measured record share"], ["Transaction volume", String(paymentCount + refundCount), "Recorded observations"], ["Fraud findings", String(findings.filter((row) => row.status === "open").length), "Open findings"]].map(([label, value, note]) => <article className="metric-card" key={label}><div className="metric-top"><span>{label}</span><ShoppingCart size={15}/></div><div className="metric-number">{value}</div><small>{note}</small></article>)}
    </section>
    <section className="panel commerce-workspace">
      <div className="panel-heading"><div><div className="panel-kicker">RECORDED TRANSACTIONS</div><h2>{page.total} matching records</h2></div><Link className="subtle-link" href="/platform/fraud">Open fraud intelligence</Link></div>
      {loading ? <div className="module-empty"><ShoppingCart size={21}/><strong>Loading commerce records</strong></div> : page.items.length === 0 ? <div className="module-empty"><ShoppingCart size={21}/><strong>No matching transactions</strong><span>Adjust filters or add persisted commerce records.</span></div> :
        <div className="table-wrap"><table className="module-table commerce-table"><thead><tr><th>Occurred</th><th>Kind</th><th>Account</th><th>Order</th><th>Currency</th><th>Amount</th><th>Action</th></tr></thead><tbody>{page.items.map((row) => <tr key={row.id}><td>{new Date(row.occurred_at).toLocaleString()}</td><td>{row.kind}</td><td>{row.account}</td><td>{row.order_reference || "—"}</td><td>{row.currency}</td><td>{row.amount_minor.toLocaleString()} minor</td><td><button className="outline-button" type="button" onClick={() => void inspect(row.id)}>Inspect</button></td></tr>)}</tbody></table></div>}
    </section>
    {selected && <section className="panel commerce-inspector"><div className="panel-heading"><div><div className="panel-kicker">TRANSACTION INSPECTOR</div><h2>{selected.kind} · {selected.external_id}</h2></div><button className="outline-button" type="button" onClick={() => setSelected(null)}>Close</button></div><dl><div><dt>Account</dt><dd>{selected.account}</dd></div><div><dt>Order reference</dt><dd>{selected.order_reference || "Unavailable"}</dd></div><div><dt>Amount</dt><dd>{selected.amount_minor.toLocaleString()} {selected.currency}</dd></div><div><dt>Device</dt><dd>{selected.device || "Unavailable"}</dd></div><div><dt>Source evidence</dt><dd>{selected.evidence ? JSON.stringify(selected.evidence) : "Unavailable"}</dd></div><div><dt>Fraud finding</dt><dd>{selected.finding ? `${selected.finding.status} · score ${selected.finding.score}` : "No linked refund finding"}</dd></div></dl></section>}
  </main>;
}
