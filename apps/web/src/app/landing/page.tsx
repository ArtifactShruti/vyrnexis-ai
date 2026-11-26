import Link from "next/link";

export default function LandingPage() {
  return <main className="landing-page">
    <header className="landing-nav">
      <Link className="auth-brand" href="/landing" aria-label="Vyrnexis home">
        <span className="auth-brand-symbol"><svg viewBox="0 0 36 36" aria-hidden="true"><path d="M18 4 29.5 10.5v13L18 30 6.5 23.5v-13L18 4Z"/><path d="m11 18 4.5 4.5L25 13M18 4v8m11.5-1.5-7 4m-16 0 7 4M18 30v-8"/><circle cx="18" cy="12" r="2"/><circle cx="23.5" cy="14.5" r="2"/><circle cx="13" cy="18" r="2"/></svg></span>
        <span><strong>VYRNEXIS</strong><small>Intelligence Beyond Detection</small></span>
      </Link>
      <nav aria-label="Landing navigation"><Link href="/login">Sign in</Link><Link className="primary-button" href="/register">Create workspace</Link></nav>
    </header>
    <section className="landing-hero">
      <div className="landing-kicker">ENTERPRISE INTELLIGENCE PLATFORM</div>
      <h1>Investigate evidence.<br/><span>Connect the intelligence.</span></h1>
      <p>VYRNEXIS brings security, fraud, forensic, and operational records into one tenant-controlled investigation workspace.</p>
      <div className="landing-actions"><Link className="primary-button" href="/login">Open workspace</Link><Link className="outline-button" href="/register">Create organization</Link></div>
    </section>
  </main>;
}
