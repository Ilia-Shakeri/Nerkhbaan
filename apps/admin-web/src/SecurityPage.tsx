import { useState } from "react";

import { adminApi } from "./api";
import type { AdminProfile, JsonRecord } from "./types";
import { PageState, Panel, RecordDetails, useOperation, useResource } from "./ui";

export function SecurityPage({
  profile,
  onChanged,
}: {
  profile: AdminProfile;
  onChanged: () => Promise<void>;
}) {
  const status = useResource<JsonRecord>("/auth/mfa", {});
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthCode, setReauthCode] = useState("");
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<JsonRecord | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const operation = useOperation();
  const securityLocked = operation.busy || status.loading || Boolean(status.error);
  const reauthenticate = async () => {
    await adminApi.reauthenticate(reauthPassword, reauthCode);
    setReauthPassword("");
    setReauthCode("");
  };
  const password = (event: React.FormEvent) => {
    event.preventDefault();
    void operation.run(async () => {
      if (newPassword !== confirmation)
        throw new Error("New password confirmation does not match");
      await adminApi.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setMessage("Password changed. Other sessions closed.");
      await onChanged();
    });
  };
  const enroll = () =>
    operation.run(async () => {
      await reauthenticate();
      setEnrollment(await adminApi.post("/auth/mfa/enroll"));
      setBackupCodes([]);
      setMessage(
        "Add this account to your authenticator, then confirm a current code.",
      );
    });
  const confirm = (event: React.FormEvent) => {
    event.preventDefault();
    void operation.run(async () => {
      const result = await adminApi.post<JsonRecord>("/auth/mfa/confirm", {
        code,
      });
      setCode("");
      setEnrollment(null);
      setBackupCodes(result.backup_codes);
      setMessage(
        "MFA enabled. Store the recovery codes now; they are shown once.",
      );
      await status.reload();
      await onChanged();
    });
  };
  const maintain = (action: "disable" | "recovery-codes") =>
    operation.run(async () => {
      await reauthenticate();
      const result = await adminApi.post<JsonRecord>(`/auth/mfa/${action}`, {
        code,
      });
      setCode("");
      setBackupCodes(result.backup_codes || []);
      setMessage(
        action === "disable"
          ? "MFA disabled. Other administrator sessions closed."
          : "Old recovery codes replaced. Store the new codes now.",
      );
      await status.reload();
      await onChanged();
    });
  return (
    <div className="page-stack">
      {operation.error && (
        <div className="error-banner" role="alert">
          {operation.error}
          {operation.reloadRequired && <><p>The outcome may be unknown. Reload your current security state before another action.</p><button type="button" className="button secondary" onClick={() => window.location.reload()}>Reload current data</button></>}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {profile.mfa_required && !profile.mfa_enabled && (
        <div className="error-banner">
          MFA enrollment is required before using operational pages.
        </div>
      )}
      <Panel title="Change administrator password">
        <form onSubmit={password} className="page-stack">
          <div className="filter-grid">
            <label>
              Current password
              <input
                type="password"
                required
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </label>
            <label>
              New password
              <input
                type="password"
                required
                minLength={14}
                maxLength={128}
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </label>
            <label>
              Confirm password
              <input
                type="password"
                required
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </label>
          </div>
          <p>
            14–128 characters, with uppercase, lowercase, number and symbol.
          </p>
          <button className="button primary" disabled={operation.busy}>
            Change password
          </button>
        </form>
      </Panel>
      <Panel title="Authenticator and recovery">
        <PageState loading={status.loading} error={status.error} onRetry={() => void status.reload()} />
        <RecordDetails value={status.data} />
        <div className="filter-grid">
          <label>
            Current password for sensitive changes
            <input
              type="password"
              autoComplete="current-password"
              value={reauthPassword}
              onChange={(event) => setReauthPassword(event.target.value)}
            />
          </label>
          {status.data.enabled && (
            <label>
              Current authenticator or recovery code
              <input
                value={reauthCode}
                autoComplete="one-time-code"
                onChange={(event) => setReauthCode(event.target.value)}
              />
            </label>
          )}
        </div>
        {!status.data.enabled && !enrollment && (
          <button
            className="button secondary"
            disabled={securityLocked || !reauthPassword}
            onClick={() => void enroll()}
          >
            Start MFA enrollment
          </button>
        )}
        {enrollment && (
          <form className="page-stack" onSubmit={confirm}>
            <p>
              Manual setup key:{" "}
              <code className="secret-copy">{enrollment.secret}</code>
            </p>
            <p>
              Use a 6-digit TOTP account, 30-second period, SHA1. Keep this key
              private.
            </p>
            <details>
              <summary>Authenticator URI</summary>
              <code className="secret-copy">{enrollment.otpauth_uri}</code>
            </details>
            <label>
              Authenticator code
              <input
                required
                pattern="[0-9]{6}"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            <button
              className="button primary"
              disabled={securityLocked || code.length !== 6}
            >
              Confirm enrollment
            </button>
          </form>
        )}
        {status.data.enabled && (
          <>
            <label>
              New code for the operation
              <input
                value={code}
                autoComplete="one-time-code"
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            <p>
              Each code works once. After re-authentication, use a different
              recovery code or wait for the next authenticator code.
            </p>
            <div className="row-actions">
              <button
                className="button secondary"
                disabled={
                  securityLocked || !reauthPassword || !reauthCode || !code
                }
                onClick={() => void maintain("recovery-codes")}
              >
                Replace recovery codes
              </button>
              {!profile.mfa_required && (
                <button
                  className="button danger"
                  disabled={
                    securityLocked || !reauthPassword || !reauthCode || !code
                  }
                  onClick={() => void maintain("disable")}
                >
                  Disable MFA
                </button>
              )}
            </div>
          </>
        )}
        {backupCodes.length > 0 && (
          <div className="recovery-codes">
            <h3>Recovery codes — shown once</h3>
            <ul>
              {backupCodes.map((item) => (
                <li key={item}>
                  <code>{item}</code>
                </li>
              ))}
            </ul>
            <button className="button ghost" onClick={() => setBackupCodes([])}>
              I stored the codes; hide them
            </button>
          </div>
        )}
      </Panel>
    </div>
  );
}
