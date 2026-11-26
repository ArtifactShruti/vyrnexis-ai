"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { request, workspace } from "@/lib/ai-workspace";

type Settings = {
  provider: string; model: string | null; mode: string; allow_model_context: boolean;
  max_output_tokens: number; daily_budget_micros: number; timeout_seconds: number;
};
type Usage = { id: string; provider: string; model: string; status: string; error_code: string | null;
  input_tokens: number | null; output_tokens: number | null; charged_micros: number; created_at: string };
type Data = { settings: Settings; providers: Record<string, { configured: boolean; enabled: boolean }>; recent_usage: Usage[] };
const names = { openai: "OpenAI-compatible", anthropic: "Anthropic Claude", gemini: "Google Gemini", ollama: "Local Ollama" };

export default function AiSettingsWorkspace() {
  const [data, setData] = useState<Data>();
  const [form, setForm] = useState<Settings>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  async function load() {
    const stored = await workspace<Data>("ai/settings");
    setData(stored);
    setForm(stored.settings);
  }
  useEffect(() => { void load().catch(cause => setError(cause.message)); }, []);

  async function act(action: "save" | "test") {
    if (!form) return;
    setBusy(true); setError(""); setStatus("");
    try {
      if (action === "save") {
        await workspace("ai/settings", request("PUT", { ...form, model: form.model?.trim() || null }));
        setStatus("Settings saved.");
      } else {
        const result = await workspace<{ status: string }>("ai/test", request("POST"));
        setStatus(result.status === "connected" ? "The saved connection resolved the selected model." : `Connection status · ${result.status.replaceAll("_", " ")}`);
      }
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Settings request failed."); }
    finally { setBusy(false); }
  }

  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>AI settings</h1><p>Control which model can receive authorized context and set a daily spending limit.</p></div><Link className="agents-refresh" href="/platform/copilot">Open Copilot</Link></header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    {status && <p className="agents-success" role="status">{status}</p>}
    {!form && !error && <p role="status">Loading settings…</p>}
    {form && data && <div className="ai-settings-grid">
      <section className="panel intake-panel"><h2>Model and permissions</h2>
        <form className="detection-form" onSubmit={event => { event.preventDefault(); void act("save"); }}>
          <label>Execution mode<select value={form.mode} onChange={event => setForm({ ...form, mode: event.target.value })}>
            <option value="deterministic">Deterministic</option><option value="assisted">Model-assisted</option>
            <option value="hybrid">Hybrid · available for Copilot requests</option>
          </select></label>
          <label>Provider<select value={form.provider} onChange={event => setForm({ ...form, provider: event.target.value, model: null })}>
            {Object.entries(names).map(([key, name]) => <option value={key} key={key}>{name}</option>)}
          </select></label>
          <label>Model ID<input value={form.model || ""} maxLength={120} required={form.mode !== "deterministic"} onChange={event => setForm({ ...form, model: event.target.value })}/></label>
          <label>Output token limit<input type="number" required min={64} max={2048} value={form.max_output_tokens} onChange={event => setForm({ ...form, max_output_tokens: Number(event.target.value) })}/></label>
          <label>Daily budget in USD<input type="number" required min={0} max={100} step="0.000001" value={form.daily_budget_micros / 1_000_000} onChange={event => setForm({ ...form, daily_budget_micros: Math.round(Number(event.target.value) * 1_000_000) })}/></label>
          <label>Request timeout in seconds<input type="number" required min={3} max={40} value={form.timeout_seconds} onChange={event => setForm({ ...form, timeout_seconds: Number(event.target.value) })}/></label>
          <label className="ai-check"><input type="checkbox" checked={form.allow_model_context} onChange={event => setForm({ ...form, allow_model_context: event.target.checked })}/> Allow authorized questions and source excerpts to be sent to the configured model</label>
          <div className="intake-actions"><button className="primary-button" disabled={busy}>Save settings</button><button className="agents-refresh" type="button" disabled={busy || !data.settings.model} onClick={() => void act("test")}>Test saved connection</button></div>
        </form>
      </section>
      <section className="panel intake-panel"><h2>Server connections</h2><p>Credentials are supplied by the deployment operator.</p>
        <ul className="detection-sources">{Object.entries(data.providers).map(([key, provider]) => <li key={key}><strong>{names[key as keyof typeof names]}</strong><small>{provider.configured ? "Configured" : "Configuration missing"} · {provider.enabled ? "Server enabled" : "Server disabled"}</small></li>)}</ul>
        <h2>Recent model usage</h2>
        {!data.recent_usage.length && <p>No model requests recorded.</p>}
        <ul className="detection-sources">{data.recent_usage.map(item => <li key={item.id}><strong>{item.model} · {item.status}</strong>
          <small>{item.input_tokens ?? "—"} input / {item.output_tokens ?? "—"} output tokens · ${(item.charged_micros / 1_000_000).toFixed(6)} accounted</small>
          {item.error_code && <small>{item.error_code.replaceAll("_", " ")}</small>}</li>)}</ul>
      </section>
    </div>}
  </main>;
}
