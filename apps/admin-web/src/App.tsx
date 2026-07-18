import { useEffect, useMemo, useState } from "react";

import { adminApi } from "./api";
import {
  AuditPage,
  DashboardPage,
  JobsPage,
  PricingPage,
  ProvidersPage,
  RolesPage,
  SettingsPage,
  SupportPage,
  UsersPage,
} from "./pages";
import type { AdminProfile, DangerousAction } from "./types";
import { DangerousDialog, humanError } from "./ui";

type Section = "dashboard" | "users" | "roles" | "support" | "providers" | "pricing" | "jobs" | "settings" | "audit";

const navigation: Array<{ id: Section; label: string; symbol: string; permission: string }> = [
  { id: "dashboard", label: "Operations", symbol: "◈", permission: "admin.health.read" },
  { id: "users", label: "Users", symbol: "◎", permission: "admin.users.read" },
  { id: "roles", label: "Access", symbol: "⌘", permission: "admin.roles.read" },
  { id: "support", label: "Support", symbol: "◇", permission: "admin.support.read" },
  { id: "providers", label: "Providers", symbol: "⇄", permission: "admin.providers.read" },
  { id: "pricing", label: "Pricing", symbol: "⌁", permission: "admin.pricing.read" },
  { id: "jobs", label: "Jobs & DLQ", symbol: "↻", permission: "admin.jobs.read" },
  { id: "settings", label: "Settings", symbol: "⚙", permission: "admin.settings.read" },
  { id: "audit", label: "Audit", symbol: "▤", permission: "admin.audit.read" },
];

function Login({ onSignin }: { onSignin: (profile: AdminProfile) => void }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await adminApi.signin(identifier, password);
      setPassword("");
      onSignin(result.admin);
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-brand">
        <div className="brand-seal"><span>N</span></div>
        <p className="eyebrow">NERKHBAAN CONTROL PLANE</p>
        <h1>Guard the signal.<br />Control the system.</h1>
        <p>Restricted operations surface. Every change is permission checked and audited.</p>
        <div className="auth-grid" aria-hidden="true" />
      </section>
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-top"><span className="pulse-dot" /> Secure administrator session</div>
        <h2>Sign in</h2>
        <p>Use an assigned administrator account. The URL alone grants no access.</p>
        <label>
          Username or email
          <input value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="error-banner">{error}</div>}
        <button className="button primary full" disabled={busy}>{busy ? "Checking…" : "Enter control plane"}</button>
        <small>Short session · HttpOnly cookie · Network policy aware</small>
      </form>
    </main>
  );
}

function PasswordGate({ profile, onChanged }: { profile: AdminProfile; onChanged: () => void }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setError("New password confirmation does not match");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await adminApi.changePassword(currentPassword, newPassword);
      onChanged();
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell single">
      <form className="auth-card wide" onSubmit={submit}>
        <div className="brand-seal small"><span>N</span></div>
        <p className="eyebrow">FIRST ACCESS POLICY</p>
        <h2>Change bootstrap password</h2>
        <p>{profile.full_name}, all other administrator functions stay locked until this password is replaced.</p>
        <label>Current password<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" /></label>
        <label>New password<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" /></label>
        <label>Confirm new password<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" /></label>
        <p className="policy-copy">14+ characters with uppercase, lowercase, number, and symbol.</p>
        {error && <div className="error-banner">{error}</div>}
        <button className="button primary full" disabled={busy}>Set secure password</button>
      </form>
    </main>
  );
}

export default function App() {
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [checking, setChecking] = useState(true);
  const [section, setSection] = useState<Section>("dashboard");
  const [danger, setDanger] = useState<DangerousAction | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    adminApi.me().then(setProfile).catch(() => setProfile(null)).finally(() => setChecking(false));
  }, []);

  const allowedNavigation = useMemo(
    () => navigation.filter((item) => profile?.permissions.includes(item.permission)),
    [profile],
  );

  async function signout() {
    await adminApi.signout();
    setProfile(null);
  }

  function completeDanger() {
    setDanger(null);
    setRefreshKey((value) => value + 1);
  }

  if (checking) return <div className="boot-screen"><div className="brand-seal"><span>N</span></div><span className="spinner" />Opening secure console…</div>;
  if (!profile) return <Login onSignin={setProfile} />;
  if (profile.must_change_password) {
    return <PasswordGate profile={profile} onChanged={() => adminApi.me().then(setProfile)} />;
  }

  const pageProps = { onDanger: setDanger, refreshKey };
  const pages: Record<Section, React.ReactNode> = {
    dashboard: <DashboardPage {...pageProps} />,
    users: <UsersPage {...pageProps} />,
    roles: <RolesPage {...pageProps} />,
    support: <SupportPage {...pageProps} />,
    providers: <ProvidersPage {...pageProps} />,
    pricing: <PricingPage {...pageProps} />,
    jobs: <JobsPage {...pageProps} />,
    settings: <SettingsPage {...pageProps} />,
    audit: <AuditPage {...pageProps} />,
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand"><div className="brand-seal small"><span>N</span></div><div><strong>Nerkhbaan</strong><small>Operations</small></div></div>
        <nav>
          {allowedNavigation.map((item) => (
            <button key={item.id} className={section === item.id ? "active" : ""} onClick={() => setSection(item.id)}>
              <span>{item.symbol}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-profile">
          <div className="avatar">{profile.full_name.slice(0, 1).toUpperCase()}</div>
          <div><strong>{profile.full_name}</strong><small>{profile.roles.join(" · ")}</small></div>
          <button className="icon-button" onClick={() => void signout()} title="Sign out">↪</button>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <div><p className="eyebrow">CONTROL PLANE / {section.toUpperCase()}</p><h1>{navigation.find((item) => item.id === section)?.label}</h1></div>
          <div className="session-chip"><span className="pulse-dot" /> Session ends {new Date(profile.session_expires_at).toLocaleTimeString()}</div>
        </header>
        <div className="workspace-content" key={`${section}-${refreshKey}`}>{pages[section]}</div>
      </main>
      {danger && <DangerousDialog action={danger} onClose={() => setDanger(null)} onComplete={completeDanger} />}
    </div>
  );
}
