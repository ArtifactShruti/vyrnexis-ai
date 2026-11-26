"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Bell, CheckCheck, RefreshCw, Search } from "lucide-react";
import { workspace } from "@/lib/ai-workspace";

type Notification = {
  id: string;
  category: string;
  title: string;
  resource: string;
  href: string;
  details: Record<string, unknown>;
  read: boolean;
  read_at: string | null;
  created_at: string;
};

export default function NotificationsWorkspace() {
  const [rows, setRows] = useState<Notification[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
      setRows(await workspace<Notification[]>(`notifications?${params}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Notifications are unavailable.");
    } finally { setBusy(false); }
  }, [category]);
  useEffect(() => { void load(); }, [load]);
  const visible = useMemo(() => rows.filter((row) => `${row.title} ${row.category} ${row.resource}`.toLowerCase().includes(query.toLowerCase())),
    [rows, query]);
  const markRead = async (id: string) => {
    await workspace<Notification>(`notifications/${id}/read`, { method: "POST" });
    await load();
  };
  const markAll = async () => {
    await workspace<{ marked_read: number }>("notifications/read-all", { method: "POST" });
    await load();
  };
  const categories = Array.from(new Set(rows.map((row) => row.category))).sort();
  return <main className="module-page notifications-page">
    <header className="module-heading"><div><div className="eyebrow">ACTIVITY CENTER</div><h1>Notifications</h1><p>Account-isolated notifications derived from persisted domain activity.</p></div><div className="module-actions"><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button><button className="primary-button" type="button" onClick={() => void markAll()} disabled={busy}><CheckCheck size={15}/>Mark all read</button></div></header>
    {error && <p className="notice" role="alert">{error}</p>}
    <section className="panel notifications-layout"><aside><div className="table-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search notifications"/></div><label>Category<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item}>{item}</option>)}</select></label></aside><div className="notification-list">{visible.length === 0 ? <div className="module-empty"><Bell size={22}/><strong>No notifications</strong><span>Persisted domain activity will appear here.</span></div> : visible.map((row) => <article key={row.id} className={row.read ? "read" : "unread"}><span className="notification-dot"/><div><h2>{row.title}</h2><p>{row.resource}</p><time>{new Date(row.created_at).toLocaleString()}</time></div>{row.href && <Link className="outline-button" href={row.href}>Open</Link>}{!row.read && <button type="button" className="outline-button" onClick={() => void markRead(row.id)}>Mark read</button>}</article>)}</div></section>
  </main>;
}
