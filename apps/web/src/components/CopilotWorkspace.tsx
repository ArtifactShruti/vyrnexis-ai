"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Availability, type Citation, request, workspace } from "@/lib/ai-workspace";

type Context = { id: string; title: string };
type Conversation = Context & { case_id: string | null; incident_id: string | null; updated_at: string };
type Turn = { id: string; question: string; mode: string; status: string; answer: string | null; sources: Citation[];
  model: { provider: string; model: string; prompt_version: string } | null };
type Detail = Conversation & { turns: Turn[] };
const root = "copilot/conversations";

async function streamAnswer(path: string, payload: object, onPartial: (value: string) => void) {
  const response = await fetch(`/api/workspace/${path}`, { ...request("POST", payload), cache: "no-store" });
  if (!response.ok || !response.body) {
    const info = await response.json().catch(() => ({}));
    throw new Error(info.detail || "Live generation is unavailable.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) throw new Error("The model stream ended before the final answer.");
      pending += decoder.decode(chunk.value, { stream: true });
      const events = pending.split("\n\n");
      pending = events.pop() || "";
      for (const event of events) {
        const lines = event.split("\n");
        const name = lines.find(line => line.startsWith("event: "))?.slice(7);
        const data = lines.find(line => line.startsWith("data: "))?.slice(6);
        if (!data) continue;
        const value = JSON.parse(data);
        if (name === "error") throw new Error(value.detail);
        if (name === "partial") onPartial(value.text);
        if (name === "done") return value as Turn;
      }
    }
  } finally {
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export default function CopilotWorkspace() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [detail, setDetail] = useState<Detail>();
  const [selected, setSelected] = useState("");
  const [filter, setFilter] = useState("");
  const [contexts, setContexts] = useState<{ cases: Context[]; incidents: Context[] }>({ cases: [], incidents: [] });
  const [kind, setKind] = useState("");
  const [question, setQuestion] = useState("");
  const [availability, setAvailability] = useState<Availability>();
  const [mode, setMode] = useState("record_search");
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState("");
  const [partial, setPartial] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<Citation>();
  const latestTurn = detail?.turns.at(-1);

  async function history(query = "") {
    setConversations(await workspace<Conversation[]>(`${root}?query=${encodeURIComponent(query)}`));
  }
  useEffect(() => {
    void Promise.all([
      history(), workspace<Availability>("ai/availability").then(setAvailability),
      Promise.all([
        fetch("/api/forensic/forensic-cases?limit=60").then(async reply => reply.ok ? (await reply.json()).items : []),
        fetch("/api/incidents").then(async reply => reply.ok ? await reply.json() : []),
      ]).then(([cases, incidents]) => setContexts({ cases, incidents })),
    ]).catch(cause => setError(cause.message)).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(undefined); setFocus(undefined);
    if (selected) void workspace<Detail>(`${root}/${selected}`, { signal: controller.signal }).then(setDetail)
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [selected]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Copilot request failed."); }
    finally { setBusy(false); }
  }

  async function submit(text: string) {
    if (!selected || !text.trim() || sending) return;
    const key = crypto.randomUUID();
    setSending(key); setPartial(""); setError(""); setFocus(undefined);
    try {
      const payload = {
        text: text.trim(), mode, request_key: key, acknowledge_model_context: consent,
      };
      if (mode === "model_assisted") await streamAnswer(`${root}/${selected}/stream`, payload, setPartial);
      else await workspace<Turn>(`${root}/${selected}/turns`, request("POST", payload));
      setQuestion(""); setConsent(false);
      setDetail(await workspace<Detail>(`${root}/${selected}`)); await history(filter);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Question was not completed."); }
    finally { setSending(""); setPartial(""); }
  }

  return <main className="intake-page ai-workspace">
    <Link className="subtle-link" href="/">← Command center</Link>
    <header className="intake-heading"><div><h1>Investigation Copilot</h1><p>Search authorized records and inspect the sources behind each answer.</p></div>
      <div className="intake-actions"><Link className="agents-refresh" href="/platform/knowledge">Knowledge base</Link><Link className="agents-refresh" href="/platform/ai-settings">AI settings</Link></div></header>
    {error && <p className="agents-error" role="alert">{error}</p>}
    <div className="intake-layout ai-layout">
      <aside className="panel intake-panel" aria-label="Conversation navigation"><h2>Conversations</h2>
        <form className="detection-form" onSubmit={event => { event.preventDefault(); void act(() => history(filter)); }}>
          <label>Search conversation titles<input value={filter} maxLength={120} onChange={event => setFilter(event.target.value)}/></label>
          <button className="agents-refresh" disabled={busy}>Search</button>
        </form>
        {loading && <p role="status">Loading conversations…</p>}
        {!loading && !conversations.length && <p>No conversations match.</p>}
        <div className="intake-list">{conversations.map(item => <button type="button" key={item.id} aria-pressed={item.id === selected}
          disabled={!!sending || busy} onClick={() => { setSelected(item.id); setError(""); }}><strong>{item.title}</strong>
          <small>{item.case_id ? "Forensic case" : item.incident_id ? "Incident" : "Organization records"}</small></button>)}</div>
        <details className="detection-history" open={!conversations.length}>
          <summary>New conversation</summary>
          <form className="detection-form" onSubmit={event => {
            event.preventDefault(); const element = event.currentTarget; const fields = new FormData(element);
            void act(async () => {
              const item = await workspace<Conversation>(root, request("POST", {
                title: fields.get("title"), ...(kind ? { [kind + "_id"]: fields.get("record") } : {}),
              }));
              element.reset(); setKind(""); setSelected(item.id); setFilter(""); await history();
            });
          }}>
            <label>Title<input name="title" maxLength={120} required/></label>
            <label>Context<select value={kind} onChange={event => setKind(event.target.value)}><option value="">Organization records</option>
              {!!contexts.cases.length && <option value="case">Forensic case</option>}
              {!!contexts.incidents.length && <option value="incident">Incident</option>}</select></label>
            {kind && <label>Record<select name="record" required key={kind}><option value="">Select a record</option>
              {(kind === "case" ? contexts.cases : contexts.incidents).map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select></label>}
            <button className="primary-button" disabled={busy || !!sending}>Create conversation</button>
          </form>
        </details>
      </aside>
      <section className="panel intake-panel ai-chat" aria-label="Conversation history">
        <h2>{detail?.title || "Conversation"}</h2>
        {!detail && <p>{selected ? "Loading conversation…" : "Create or select a conversation."}</p>}
        {detail && <>
          <div className="intake-actions">
            {detail.case_id && <Link className="subtle-link" href={`/platform/forensics?case=${detail.case_id}`}>Open scoped case</Link>}
            {detail.incident_id && <Link className="subtle-link" href={`/platform/incidents?id=${detail.incident_id}`}>Open scoped incident</Link>}
            <a className="agents-refresh" href={`/api/workspace/${root}/${selected}/export`}>Export JSON</a>
            <button className="agents-refresh" type="button" disabled={busy || !!sending} onClick={() => {
              if (window.confirm("Permanently delete this conversation?"))
                void act(async () => { await workspace(`${root}/${selected}`, { method: "DELETE" }); setSelected(""); await history(filter); });
            }}>Delete conversation</button>
          </div>
          {!detail.turns.length && <p>Ask about a specific incident, record, or policy.</p>}
          <ol className="ai-thread">{detail.turns.map(turn => <li className="ai-turn" key={turn.id}>
            <p className="ai-question">{turn.question}</p>
            <small>{turn.model ? `${turn.model.provider} · ${turn.model.model}` : turn.mode.replaceAll("_", " ")} · {turn.status}</small>
            <p className="ai-wrap">{turn.answer || (turn.status === "running" ? "Awaiting result." : "No answer recorded.")}</p>
            <div className="intake-actions">{turn.sources.map((item, index) =>
              <button className="agents-refresh" type="button" title={item.title} key={item.key} onClick={() => setFocus(item)}>Source {index + 1}</button>)}</div>
            {["failed", "cancelled"].includes(turn.status) && <button className="agents-refresh" type="button" disabled={!!sending} onClick={() => setQuestion(turn.question)}>Reuse question</button>}
          </li>)}</ol>
          {sending && mode === "model_assisted" && <article className="ai-turn" aria-label="Streaming model answer">
            <small>{partial ? "Provisional model output" : "Waiting for the configured model…"}</small>
            {partial && <p className="ai-wrap">{partial}</p>}
          </article>}
          <form className="detection-form" onSubmit={event => { event.preventDefault(); void submit(question); }}>
            <label>Question<textarea value={question} rows={3} minLength={2} maxLength={1000} required
              onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}
              onChange={event => setQuestion(event.target.value)}/></label>
            <label>Answer mode<select value={mode} onChange={event => { setMode(event.target.value); setConsent(false); }}>
              <option value="record_search">Record search</option><option value="model_assisted" disabled={!availability?.available}>Model-assisted</option>
            </select></label>
            {mode === "model_assisted" && <label className="ai-check"><input type="checkbox" checked={consent} required onChange={event => setConsent(event.target.checked)}/>
              Send this question and matching excerpts to {availability?.provider} for this answer</label>}
            <div className="intake-actions"><button className="primary-button" disabled={!!sending || busy}>{sending ? "Working…" : "Ask Copilot"}</button>
              {sending && <button className="agents-refresh" type="button" onClick={() => void act(async () => {
                await workspace(`${root}/${selected}/cancel/${sending}`, request("POST"));
                setDetail(await workspace<Detail>(`${root}/${selected}`));
              })}>Stop generation</button>}
            </div>
          </form>
        </>}
      </section>
      <aside className="panel intake-panel" aria-label="Supporting sources"><h2>Sources</h2>
        {!availability?.available && <p>Record search is available. Model assistance is disabled by the current configuration.</p>}
        {focus ? <article className="ai-citation"><h3>{focus.title}</h3>
          <small>{focus.kind.replaceAll("_", " ")}{focus.version ? ` · version ${focus.version} · ${focus.location}` : ""}</small>
          <p>{focus.excerpt}</p><Link className="subtle-link" href={focus.href}>Open source</Link></article> :
          <ul className="intake-list">{latestTurn?.sources.map(item => <li key={item.key}><button type="button" onClick={() => setFocus(item)}>{item.title}</button></li>)}</ul>}
        {!focus && !latestTurn?.sources.length && <p>Matching source excerpts will appear here.</p>}
      </aside>
    </div>
  </main>;
}
