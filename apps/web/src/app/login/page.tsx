"use client";

import Link from "next/link";
import { useState } from "react";
import { LockKeyhole } from "lucide-react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    setSubmitting(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const result = await response.json();
      if (!response.ok) {
        setMessage(result.detail || "Sign-in failed");
        return;
      }
      window.location.assign("/");
    } catch {
      setMessage("Authentication service is unavailable");
    } finally {
      setSubmitting(false);
    }
  }

  return <main className="auth-page">
    <form onSubmit={submit} className="auth-card">
      <Link className="auth-brand" href="/login" aria-label="Vyrnexis sign in">
        <span className="auth-brand-symbol"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 4 29.5 10.5v13L18 30 6.5 23.5v-13L18 4Z"/><path d="m11 18 4.5 4.5L25 13M18 4v8m11.5-1.5-7 4m-16 0 7 4M18 30v-8"/><circle cx="18" cy="12" r="2"/><circle cx="23.5" cy="14.5" r="2"/><circle cx="13" cy="18" r="2"/></svg></span>
        <span><strong>VYRNEXIS</strong><small>Intelligence Beyond Detection</small></span>
      </Link>
      <div className="auth-eyebrow">SECURE WORKSPACE ACCESS</div>
      <h1>Sign in</h1>
      <p className="auth-description">Access your organization intelligence workspace.</p>
      <label className="auth-field">Work email<input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@organization.com"/></label>
      <label className="auth-field">Password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password"/></label>
      <button className="auth-submit" type="submit" disabled={submitting}><LockKeyhole size={15}/>{submitting ? "Signing in..." : "Sign in securely"}</button>
      {message && <p role="alert" className="auth-error">{message}</p>}
      <div className="auth-divider"><span/></div>
      <p className="auth-footnote">Organization membership is checked by the VYRNEXIS API for each session.</p>
      <p className="auth-switch">Setting up a workspace? <Link href="/register">Create an organization</Link></p>
    </form>
    <footer className="auth-footer">VYRNEXIS AI <span>|</span> Enterprise Intelligence Platform</footer>
  </main>;
}
