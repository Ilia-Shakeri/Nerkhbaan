import { useCallback, useEffect, useState } from "react";

import { adminApi, ApiError } from "./api";
import type { DangerousAction, JsonRecord } from "./types";

export function humanError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Operation failed";
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function StatusBadge({ value }: { value: unknown }) {
  const text = formatValue(value);
  const key = text.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return <span className={`status-badge status-${key}`}>{text}</span>;
}

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <h2>{title}</h2>
        {action}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function EmptyState({ text = "No records found" }: { text?: string }) {
  return <div className="empty-state">{text}</div>;
}

export function PageState({ loading, error }: { loading: boolean; error: string }) {
  if (loading) return <div className="page-state"><span className="spinner" /> Loading current data…</div>;
  if (error) return <div className="error-banner">{error}</div>;
  return null;
}

export function DataTable({
  columns,
  rows,
  rowKey = "id",
}: {
  columns: Array<{ key: string; label: string; render?: (row: JsonRecord) => React.ReactNode }>;
  rows: JsonRecord[];
  rowKey?: string;
}) {
  if (!rows.length) return <EmptyState />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row[rowKey] ?? index)}>
              {columns.map((column) => (
                <td key={column.key}>{column.render ? column.render(row) : formatValue(row[column.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function useResource<T>(path: string, initial: T) {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await adminApi.get<T>(path));
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, setData, loading, error, reload };
}

export function DangerousDialog({
  action,
  onClose,
  onComplete,
}: {
  action: DangerousAction;
  onClose: () => void;
  onComplete: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const matches = confirmation === action.expected;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!matches || !password) return;
    setBusy(true);
    setError("");
    try {
      await adminApi.reauthenticate(password);
      await action.execute(confirmation);
      setPassword("");
      onComplete();
    } catch (reason) {
      setError(humanError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="modal danger-modal" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="danger-title">
        <div className="danger-mark">!</div>
        <h2 id="danger-title">{action.title}</h2>
        <p className="impact-copy">{action.impact}</p>
        <label>
          Current administrator password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
        </label>
        <label>
          Type <code>{action.expected}</code>
          <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" spellCheck={false} />
        </label>
        {error && <div className="error-banner">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="button danger" disabled={!matches || !password || busy}>
            {busy ? "Applying…" : "Confirm action"}
          </button>
        </div>
      </form>
    </div>
  );
}
