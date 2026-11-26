"use client";

import Link from "next/link";
import { useState } from "react";
import { ShieldCheck } from "lucide-react";

export default function RegisterPage() {
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setMessage("");
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          organization_name: form.get("organization"),
          organization_slug: String(form.get("organization")).toLowerCase().trim().replace(/[^a-z0-9]+/g, "-"),
          full_name: form.get("name"),
          email: form.get("email"),
          password: form.get("password"),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setMessage(result.detail || "Registration failed");
        return;
      }
      window.location.assign("/");
    } catch {
      setMessage("Authentication service is unavailable");
    } finally {
      setSubmitting(false);
    }
  }

  return <main className="auth-page auth-page-register">
    <form onSubmit={(event) => void submit(event)} className="auth-card auth-card-register">
      <Link className="auth-brand" href="/register" aria-label="Vyrnexis organization setup">
        <span className="auth-brand-symbol"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 4 29.5 10.5v13L18 30 6.5 23.5v-13L18 4Z"/><path d="m11 18 4.5 4.5L25 13M18 4v8m11.5-1.5-7 4m-16 0 7 4M18 30v-8"/><circle cx="18" cy="12" r="2"/><circle cx="23.5" cy="14.5" r="2"/><circle cx="13" cy="18" r="2"/></svg></span>
        <span><strong>VYRNEXIS</strong><small>Intelligence Beyond Detection</small></span>
      </Link>
      <div className="auth-eyebrow">ORGANIZATION SETUP</div>
      <h1>Create organization</h1>
      <p className="auth-description">Start an isolated workspace with an owner account.</p>
      <label className="auth-field">Organization name<input required maxLength={200} name="organization" type="text" autoComplete="organization" placeholder="Organization name"/></label>
      <label className="auth-field">Administrator name<input required maxLength={200} name="name" type="text" autoComplete="name" placeholder="Full name"/></label>
      <label className="auth-field">Work email<input required name="email" type="email" autoComplete="email" placeholder="name@organization.com"/></label>
      <label className="auth-field">Password<input required minLength={12} name="password" type="password" autoComplete="new-password" placeholder="At least 12 characters"/></label>
      <button className="auth-submit" type="submit" disabled={submitting}><ShieldCheck size={15}/>{submitting ? "Creating organization..." : "Create organization"}</button>
      {message && <p role="alert" className="auth-error">{message}</p>}
      <p className="auth-footnote">The first account becomes the organization owner. Use a unique password for this workspace.</p>
      <p className="auth-switch">Already have an account? <Link href="/login">Sign in</Link></p>
    </form>
    <footer className="auth-footer">VYRNEXIS AI <span>|</span> Enterprise Intelligence Platform</footer>
  </main>;
}
