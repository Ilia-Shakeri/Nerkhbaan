import { useCallback, useEffect, useRef, useState } from "react";

import { adminApi, ApiError } from "./api";
import type { DangerousAction, JsonRecord } from "./types";

export function humanError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Operation failed";
}

function requiresReload(reason: unknown): boolean {
  if (reason instanceof ApiError) return reason.status === 0 || reason.status === 408 || reason.status === 409 || reason.status >= 500;
  return reason instanceof TypeError || reason instanceof SyntaxError || (reason instanceof DOMException && reason.name === "AbortError");
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number")
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(
      value,
    );
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

export function PageState({
  loading,
  error,
  onRetry = () => window.location.reload(),
}: {
  loading: boolean;
  error: string;
  onRetry?: () => void;
}) {
  if (loading)
    return (
      <div className="page-state">
        <span className="spinner" /> Loading current data…
      </div>
    );
  if (error)
    return (
      <div className="error-banner" role="alert">
        {error}
        <button type="button" className="button secondary small" onClick={onRetry}>Reload current data</button>
      </div>
    );
  return null;
}

export function DataTable({
  columns,
  rows,
  rowKey = "id",
}: {
  columns: Array<{
    key: string;
    label: string;
    render?: (row: JsonRecord) => React.ReactNode;
  }>;
  rows: JsonRecord[];
  rowKey?: string;
}) {
  if (!rows.length) return <EmptyState />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row[rowKey] ?? index)}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render
                    ? column.render(row)
                    : formatValue(row[column.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function useResource<T>(path: string, initial: T, enabled = true) {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const alive = useRef(true);
  const activeRequest = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    const requestId = ++generation.current;
    activeRequest.current?.abort();
    activeRequest.current = null;
    if (!enabled) {
      setLoading(false);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      const result = await adminApi.get<T>(path, controller.signal);
      if (alive.current && generation.current === requestId) setData(result);
    } catch (reason) {
      if (!controller.signal.aborted && alive.current && generation.current === requestId)
        setError(humanError(reason));
    } finally {
      if (alive.current && generation.current === requestId) setLoading(false);
    }
  }, [path, enabled]);
  useEffect(() => {
    alive.current = true;
    void reload();
    return () => {
      alive.current = false;
      generation.current++;
      activeRequest.current?.abort();
      activeRequest.current = null;
    };
  }, [reload]);
  return { data, setData, loading, error, reload };
}

export function useOperation(mutates = true) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  const blocked = useRef(false);
  const [reloadRequired, setReloadRequired] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const run = async (operation: () => Promise<void>) => {
    if (running.current || blocked.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (reason) {
      if (alive.current) {
        setError(humanError(reason));
        if (mutates && requiresReload(reason)) {
          blocked.current = true;
          setReloadRequired(true);
        }
      }
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  return { busy: busy || reloadRequired, error, run, reloadRequired };
}

export function Pagination({
  offset,
  limit,
  total,
  onChange,
  busy = false,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (value: number) => void;
  busy?: boolean;
}) {
  return (
    <div className="pagination">
      <button
        className="button ghost small"
        disabled={busy || offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span>
        {total ? offset + 1 : 0}–{Math.min(offset + limit, total)} / {total}
      </span>
      <button
        className="button ghost small"
        disabled={busy || offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        Next
      </button>
    </div>
  );
}

export function RecordDetails({
  value,
}: {
  value: JsonRecord | null | undefined;
}) {
  if (!value) return <EmptyState />;
  return (
    <dl className="detail-list">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>{formatValue(item)}</dd>
        </div>
      ))}
    </dl>
  );
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
  const [mfaCode, setMfaCode] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadRequired, setReloadRequired] = useState(false);
  const submitting = useRef(false);
  const blocked = useRef(false);
  const matches = confirmation === action.expected;
  const dialogRef = useRef<HTMLFormElement>(null);
  const close = () => {
    if (submitting.current) return;
    if (blocked.current) onComplete();
    else onClose();
  };
  const onCloseRef = useRef(close);
  const busyRef = useRef(busy);
  onCloseRef.current = close;
  busyRef.current = busy;

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const dialog = dialogRef.current;
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    focusable()[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busyRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current || blocked.current || !matches || !password) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    let actionStarted = false;
    try {
      await adminApi.reauthenticate(password, mfaCode);
      actionStarted = true;
      await action.execute(confirmation);
      setPassword("");
      onComplete();
    } catch (reason) {
      setError(humanError(reason));
      if (actionStarted && requiresReload(reason)) {
        blocked.current = true;
        setReloadRequired(true);
      }
    } finally {
      setPassword("");
      setMfaCode("");
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        ref={dialogRef}
        className="modal danger-modal"
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="danger-title"
        aria-describedby="danger-impact"
      >
        <div className="danger-mark">!</div>
        <h2 id="danger-title">{action.title}</h2>
        <p className="impact-copy" id="danger-impact">
          {action.impact}
        </p>
        <label>
          Current administrator password
          <input
            type="password"
            disabled={busy || reloadRequired}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label>
          Authenticator or recovery code (if enabled)
          <input
            value={mfaCode}
            disabled={busy || reloadRequired}
            onChange={(event) => setMfaCode(event.target.value)}
            autoComplete="one-time-code"
          />
        </label>
        <label>
          Type <code>{action.expected}</code>
          <input
            value={confirmation}
            disabled={busy || reloadRequired}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        {reloadRequired && <p role="status">The action may have completed or its data changed. Close and reload current data before another action.</p>}
        <div className="modal-actions">
          <button
            type="button"
            className="button ghost"
            onClick={close}
            disabled={busy}
          >
            {reloadRequired ? "Close and reload" : "Cancel"}
          </button>
          <button
            type="submit"
            className="button danger"
            disabled={!matches || !password || busy || reloadRequired}
          >
            {busy ? "Applying…" : "Confirm action"}
          </button>
        </div>
      </form>
    </div>
  );
}
