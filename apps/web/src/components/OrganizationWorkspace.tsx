"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldCheck } from "lucide-react";

type Configuration = {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  currency: string;
  industry: string;
  branding: Record<string, unknown>;
  settings: Record<string, unknown>;
  onboarding: Record<string, unknown>;
};

export default function OrganizationWorkspace({ onboarding = false }: { onboarding?: boolean }) {
  const [data, setData] = useState<Configuration | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [currency, setCurrency] = useState("USD");
  const [industry, setIndustry] = useState("");
  const [profileComplete, setProfileComplete] = useState(false);
  const [teamReady, setTeamReady] = useState(false);
  const [securityReady, setSecurityReady] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/workspace/admin/organization", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Organization settings unavailable.");
      setData(body);
      setName(body.name);
      setTimezone(body.timezone);
      setCurrency(body.currency);
      setIndustry(body.industry);
      const progress = body.onboarding || {};
      setProfileComplete(Boolean(progress.profileComplete));
      setTeamReady(Boolean(progress.teamReady));
      setSecurityReady(Boolean(progress.securityReady));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Organization settings unavailable.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const response = await fetch("/api/workspace/admin/organization", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name, timezone, currency: currency.toUpperCase(), industry,
          branding: data?.branding || {},
          settings: data?.settings || {},
          onboarding: { profileComplete, teamReady, securityReady, resumeAt: new Date().toISOString() },
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Organization settings could not be saved.");
      setData(body);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Organization settings could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const checklist = [
    ["Organization profile", profileComplete, setProfileComplete],
    ["Initial team setup", teamReady, setTeamReady],
    ["Security configuration", securityReady, setSecurityReady],
  ] as const;

  return <main className="module-page">
    <header className="module-heading"><div><div className="eyebrow">ORGANIZATION ADMINISTRATION</div><h1>{onboarding ? "Organization onboarding" : "Organization settings"}</h1><p>Configure tenant profile and persisted operational preferences.</p></div><button className="outline-button" type="button" onClick={() => void load()} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""}/>Refresh</button></header>
    {error && <div className="notice" role="alert"><ShieldCheck size={16}/><div><strong>Configuration unavailable</strong><span>{error}</span></div></div>}
    {saved && <div className="notice success-notice" role="status"><CheckCircle2 size={16}/><div><strong>Configuration saved</strong><span>Organization preferences were persisted and audited.</span></div></div>}
    <form className="organization-layout" onSubmit={save}>
      <section className="panel organization-form">
        <div className="panel-heading"><div><div className="panel-kicker">TENANT PROFILE</div><h2>Core configuration</h2></div></div>
        <label>Organization name<input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)}/></label>
        <div className="organization-form-grid">
          <label>Timezone<select value={timezone} onChange={(event) => setTimezone(event.target.value)}><option>UTC</option><option>America/New_York</option><option>Europe/London</option><option>Asia/Kolkata</option><option>Asia/Singapore</option></select></label>
          <label>Default currency<select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>USD</option><option>EUR</option><option>GBP</option><option>INR</option></select></label>
        </div>
        <label>Industry<input maxLength={100} value={industry} onChange={(event) => setIndustry(event.target.value)} placeholder="For example: Financial services"/></label>
        {onboarding && <div className="onboarding-checklist">{checklist.map(([label, checked, setChecked]) => <label key={label}><input type="checkbox" checked={checked} onChange={(event) => setChecked(event.target.checked)}/><span><strong>{label}</strong><small>{checked ? "Completed" : "Not completed"}</small></span></label>)}</div>}
        <button className="primary-button organization-save" type="submit" disabled={busy}><ShieldCheck size={15}/>{busy ? "Saving..." : "Save organization"}</button>
      </section>
      <aside className="panel organization-summary"><div className="panel-kicker">CURRENT WORKSPACE</div><h2>{data?.name || "Loading organization"}</h2><dl><div><dt>Slug</dt><dd>{data?.slug || "-"}</dd></div><div><dt>Timezone</dt><dd>{timezone}</dd></div><div><dt>Currency</dt><dd>{currency}</dd></div></dl></aside>
    </form>
  </main>;
}
