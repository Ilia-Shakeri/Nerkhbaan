import { useEffect, useMemo, useRef, useState } from "react";

import { adminApi } from "./api";
import {
  AuditPage,
  AlertsPage,
  BackupsPage,
  DashboardPage,
  JobsPage,
  DlqPage,
  TelegramPage,
  PricingPage,
  ProvidersPage,
  RolesPage,
  SettingsPage,
  SupportPage,
  UsersPage,
} from "./pages";
import type { AdminProfile, DangerousAction } from "./types";
import { DangerousDialog, humanError } from "./ui";
import { SecurityPage } from "./SecurityPage";
import { CommunicationsPage } from "./CommunicationsPage";

type Section =
  | "dashboard"
  | "users"
  | "roles"
  | "support"
  | "providers"
  | "telegram"
  | "dlq"
  | "pricing"
  | "jobs"
  | "settings"
  | "audit"
  | "alerts"
  | "communications"
  | "backups"
  | "security";

const navigation: Array<{
  id: Section;
  label: string;
  symbol: string;
  permission: string;
}> = [
  {
    id: "dashboard",
    label: "Operations",
    symbol: "◈",
    permission: "admin.health.read",
  },
  { id: "users", label: "Users", symbol: "◎", permission: "admin.users.read" },
  { id: "roles", label: "Access", symbol: "⌘", permission: "admin.roles.read" },
  {
    id: "support",
    label: "Support",
    symbol: "◇",
    permission: "admin.support.read",
  },
  {
    id: "telegram",
    label: "Telegram",
    symbol: "◇",
    permission: "admin.telegram.read",
  },
  {
    id: "dlq",
    label: "Dead-letter queue",
    symbol: "↻",
    permission: "admin.dlq.read",
  },
  {
    id: "providers",
    label: "Providers",
    symbol: "⇄",
    permission: "admin.providers.read",
  },
  {
    id: "pricing",
    label: "Pricing",
    symbol: "⌁",
    permission: "admin.pricing.read",
  },
  {
    id: "jobs",
    label: "Jobs & DLQ",
    symbol: "↻",
    permission: "admin.jobs.read",
  },
  {
    id: "settings",
    label: "Settings",
    symbol: "⚙",
    permission: "admin.settings.read",
  },
  {
    id: "alerts",
    label: "Alerts",
    symbol: "!",
    permission: "admin.alerts.read",
  },
  {
    id: "communications",
    label: "مرکز ارتباطات",
    symbol: "◌",
    permission: "admin.settings.read",
  },
  {
    id: "backups",
    label: "Backup evidence",
    symbol: "◫",
    permission: "admin.health.read",
  },
  { id: "security", label: "My security", symbol: "◉", permission: "" },
  { id: "audit", label: "Audit", symbol: "▤", permission: "admin.audit.read" },
];

const sectionFromHash = (): Section => {
  const candidate = window.location.hash.replace(/^#\/?/, "") as Section;
  return navigation.some((item) => item.id === candidate)
    ? candidate
    : "dashboard";
};

function Login({
  onSignin,
  initialError = "",
}: {
  onSignin: (profile: AdminProfile) => void;
  initialError?: string;
}) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await adminApi.signin(identifier, password, mfaCode);
      setPassword("");
      sessionStorage.removeItem("admin-logout-pending");
      onSignin(result.admin);
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-brand">
        <div className="brand-seal">
          <span>N</span>
        </div>
        <p className="eyebrow">NERKHBAAN CONTROL PLANE</p>
        <h1>
          Guard the signal.
          <br />
          Control the system.
        </h1>
        <p>
          Restricted operations surface. Every change is permission checked and
          audited.
        </p>
        <div className="auth-grid" aria-hidden="true" />
      </section>
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-top">
          <span className="pulse-dot" /> Secure administrator session
        </div>
        <h2>Sign in</h2>
        <p>
          Use an assigned administrator account. The URL alone grants no access.
        </p>
        <label>
          Username or email
          <input
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label>
          Authenticator or recovery code (if enabled)
          <input
            autoComplete="one-time-code"
            value={mfaCode}
            onChange={(event) => setMfaCode(event.target.value)}
          />
        </label>
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        <button className="button primary full" disabled={busy}>
          {busy ? "Checking…" : "Enter control plane"}
        </button>
        <small>Short session · HttpOnly cookie · Network policy aware</small>
      </form>
    </main>
  );
}

function PasswordGate({
  profile,
  onChanged,
}: {
  profile: AdminProfile;
  onChanged: () => void | Promise<void>;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (newPassword !== confirmation) {
      setError("New password confirmation does not match");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      await adminApi.changePassword(currentPassword, newPassword);
      await onChanged();
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell single">
      <form className="auth-card wide" onSubmit={submit}>
        <div className="brand-seal small">
          <span>N</span>
        </div>
        <p className="eyebrow">FIRST ACCESS POLICY</p>
        <h2>Change bootstrap password</h2>
        <p>
          {profile.full_name}, all other administrator functions stay locked
          until this password is replaced.
        </p>
        <label>
          Current password
          <input
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label>
          New password
          <input
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="new-password"
          />
        </label>
        <p className="policy-copy">
          14+ characters with uppercase, lowercase, number, and symbol.
        </p>
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        <button className="button primary full" disabled={busy}>
          Set secure password
        </button>
      </form>
    </main>
  );
}

export default function App() {
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [checking, setChecking] = useState(true);
  const [section, setSection] = useState<Section>(sectionFromHash);
  const [danger, setDanger] = useState<DangerousAction | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [logoutError, setLogoutError] = useState("");

  useEffect(() => {
    if (sessionStorage.getItem("admin-logout-pending")) {
      adminApi
        .signout()
        .then(() => sessionStorage.removeItem("admin-logout-pending"))
        .catch(() =>
          setLogoutError(
            "Server logout is pending. Reconnect to close the previous session.",
          ),
        )
        .finally(() => setChecking(false));
    } else {
      adminApi
        .me()
        .then(setProfile)
        .catch(() => setProfile(null))
        .finally(() => setChecking(false));
    }
  }, []);

  useEffect(() => {
    const expired = () => {
      setProfile(null);
      setDanger(null);
    };
    window.addEventListener("admin-session-expired", expired);
    return () => window.removeEventListener("admin-session-expired", expired);
  }, []);

  useEffect(() => {
    const syncSection = () => setSection(sectionFromHash());
    window.addEventListener("hashchange", syncSection);
    return () => window.removeEventListener("hashchange", syncSection);
  }, []);

  const selectSection = (nextSection: Section) => {
    if (window.location.hash !== `#/${nextSection}`)
      window.location.hash = `/${nextSection}`;
    setSection(nextSection);
  };

  const allowedNavigation = useMemo(
    () =>
      navigation.filter(
        (item) =>
          !item.permission ||
          (!(profile?.mfa_required && !profile?.mfa_enabled) &&
            profile?.permissions.includes(item.permission)),
      ),
    [profile],
  );

  useEffect(() => {
    if (!profile || allowedNavigation.some((item) => item.id === section))
      return;
    const fallback = allowedNavigation[0]?.id ?? "dashboard";
    if (window.location.hash !== `#/${fallback}`)
      window.location.hash = `/${fallback}`;
    setSection(fallback);
  }, [allowedNavigation, profile, section]);

  async function signout() {
    sessionStorage.setItem("admin-logout-pending", "1");
    try {
      await adminApi.signout();
      sessionStorage.removeItem("admin-logout-pending");
      setLogoutError("");
    } catch {
      setLogoutError(
        "Local session cleared. Server logout is pending; reconnect to close it.",
      );
    } finally {
      setProfile(null);
      setDanger(null);
    }
  }

  function completeDanger() {
    setDanger(null);
    setRefreshKey((value) => value + 1);
  }

  if (checking)
    return (
      <div className="boot-screen">
        <div className="brand-seal">
          <span>N</span>
        </div>
        <span className="spinner" />
        Opening secure console…
      </div>
    );
  if (!profile)
    return <Login onSignin={setProfile} initialError={logoutError} />;
  if (profile.must_change_password) {
    return (
      <PasswordGate
        profile={profile}
        onChanged={() => adminApi.me().then(setProfile)}
      />
    );
  }

  const pageProps = {
    onDanger: setDanger,
    refreshKey,
    permissions: profile.permissions,
  };
  const visibleSection = allowedNavigation.some((item) => item.id === section)
    ? section
    : allowedNavigation[0]?.id || "security";
  const pages: Record<Section, React.ReactNode> = {
    dashboard: <DashboardPage {...pageProps} />,
    users: <UsersPage {...pageProps} />,
    roles: <RolesPage {...pageProps} />,
    support: <SupportPage {...pageProps} />,
    providers: <ProvidersPage {...pageProps} />,
    telegram: <TelegramPage {...pageProps} />,
    dlq: <DlqPage {...pageProps} />,
    pricing: <PricingPage {...pageProps} />,
    jobs: <JobsPage {...pageProps} />,
    settings: <SettingsPage {...pageProps} />,
    audit: <AuditPage {...pageProps} />,
    alerts: <AlertsPage {...pageProps} />,
    communications: <CommunicationsPage {...pageProps} client={adminApi} />,
    backups: <BackupsPage {...pageProps} />,
    security: (
      <SecurityPage
        profile={profile}
        onChanged={async () => {
          setProfile(await adminApi.me());
        }}
      />
    ),
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-seal small">
            <span>N</span>
          </div>
          <div>
            <strong>نرخ‌بان</strong>
            <small>پنل مدیریت</small>
          </div>
        </div>
        <nav>
          {allowedNavigation.map((item) => (
            <button
              key={item.id}
              className={section === item.id ? "active" : ""}
              onClick={() => selectSection(item.id)}
              aria-current={section === item.id ? "page" : undefined}
              title={item.label}
            >
              <span>{item.symbol}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-profile">
          <div className="avatar">
            {profile.full_name.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{profile.full_name}</strong>
            <small>{profile.roles.join(" · ")}</small>
          </div>
          <button
            className="icon-button"
            onClick={() => void signout()}
            title="Sign out"
            aria-label="Sign out"
          >
            ↪
          </button>
        </div>
      </aside>
      <main className="workspace">
        <header className="workspace-header" dir={section === "communications" ? "rtl" : undefined}>
          <div>
            <p className="eyebrow">{section === "communications" ? "مدیریت هشدار و تماس" : `CONTROL PLANE / ${section.toUpperCase()}`}</p>
            <h1>{navigation.find((item) => item.id === section)?.label}</h1>
          </div>
          <div className="session-chip">
            <span className="pulse-dot" /> Session ends{" "}
            {new Date(profile.session_expires_at).toLocaleTimeString()}
          </div>
        </header>
        <div
          className="workspace-content"
          key={`${visibleSection}-${refreshKey}`}
        >
          {pages[visibleSection]}
        </div>
      </main>
      {danger && (
        <DangerousDialog
          action={danger}
          onClose={() => setDanger(null)}
          onComplete={completeDanger}
        />
      )}
    </div>
  );
}
