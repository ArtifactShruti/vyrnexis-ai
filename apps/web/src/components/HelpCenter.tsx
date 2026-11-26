"use client";

import { useMemo, useState } from "react";
import { BookOpen, Search } from "lucide-react";

const articles = [
  { category: "Getting started", title: "Organization setup", body: "Create an organization, configure timezone and default currency, save onboarding progress, and create users only through tenant-authorized administration." },
  { category: "Security", title: "Authentication and sessions", body: "Sign in with an Argon2id password account. Access and refresh tokens are server-managed; revoked sessions cannot renew access." },
  { category: "Security", title: "API credentials", body: "Create read-only scoped API credentials in Developer API. Store the issued secret immediately. It is not displayed again after creation." },
  { category: "Operations", title: "Security Operations", body: "Submit authentication observations, review detection alerts, and confirm incidents only after analyst review. Detection is tenant-owned." },
  { category: "Operations", title: "Threat Intelligence", body: "Record IP, domain, URL, or file-hash indicators with analyst classification and provenance. Indicator classification is not inferred maliciousness." },
  { category: "Operations", title: "Asset and incident management", body: "Assets support lifecycle, assignment, vulnerability findings, and history. Incidents support tenant assignments and status transitions." },
  { category: "Forensics", title: "Evidence and custody", body: "Evidence uploads preserve source bytes and digests. Enrolled evidence must be exported through forensic custody workflows." },
  { category: "Investigation", title: "Nexus and deterministic agents", body: "Nexus tasks are bounded local or worker-based analyses. Provider interpretations are separate from persisted deterministic findings." },
  { category: "AI", title: "Copilot and citations", body: "Copilot combines deterministic and optional retrieval context. Revoked or deleted documents are excluded before saved citations are resolved." },
  { category: "Automation", title: "Workflow Studio", body: "Publish executable workflow definitions, approve human steps, monitor executions, and replay failed runs within authorization rules." },
  { category: "Analytics", title: "E-commerce and Business Intelligence", body: "Commerce totals use recorded payment/refund observations in original currencies. Unsupported profitability, acquisition, and forecast metrics are not invented." },
  { category: "Reports", title: "Reports Center", body: "Generate snapshots from supported tenant modules. Reports store source references and integrity hashes. JSON and CSV exports are implemented; PDF is not centralized." },
  { category: "Platform", title: "System health", body: "The observability page shows current database, Redis, worker, queue, execution, and ingestion probe results. It does not claim uptime or historical latency." },
  { category: "Troubleshooting", title: "Known limitations", body: "Live model validation, hosted CI, independent security review, signed-in visual acceptance, MFA, billing providers, and immutable evidence storage require separate deployment authorization." },
];

export default function HelpCenter() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const categories = ["All", ...Array.from(new Set(articles.map((article) => article.category)))];
  const visible = useMemo(() => articles.filter((article) =>
    (category === "All" || article.category === category)
    && `${article.category} ${article.title} ${article.body}`.toLowerCase().includes(query.toLowerCase())),
  [query, category]);
  return <main className="module-page help-page">
    <header className="module-heading"><div><div className="eyebrow">PRODUCT DOCUMENTATION</div><h1>Help center</h1><p>Searchable guidance based on currently implemented VYRNEXIS functionality.</p></div></header>
    <section className="help-layout"><aside className="panel help-nav"><div className="table-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documentation"/></div><div className="help-categories">{categories.map((item) => <button type="button" key={item} className={category === item ? "selected" : ""} onClick={() => setCategory(item)}>{item}</button>)}</div></aside><section className="help-results">{visible.map((article) => <article className="panel" key={article.title}><div className="panel-kicker">{article.category}</div><h2><BookOpen size={16}/>{article.title}</h2><p>{article.body}</p></article>)}</section></section>
  </main>;
}
