import { useEffect, useMemo, useState } from "react";

import { adminApi } from "./api";
import type { DangerousAction, JsonRecord } from "./types";
import {
  DataTable,
  EmptyState,
  PageState,
  Panel,
  StatusBadge,
  formatValue,
  humanError,
  useResource,
} from "./ui";

interface PageProps {
  onDanger: (action: DangerousAction) => void;
  refreshKey: number;
}

function Metric({ label, value, tone = "gold" }: { label: string; value: unknown; tone?: string }) {
  return <article className={`metric metric-${tone}`}><span>{label}</span><strong>{formatValue(value)}</strong></article>;
}

export function DashboardPage({ refreshKey }: PageProps) {
  const resource = useResource<JsonRecord>(`/dashboard?refresh=${refreshKey}`, {});
  const data = resource.data;
  const backlogs = data.backlogs || {};
  const counts = data.counts || {};
  const lastRows = Object.entries(data.background_refresh?.last_by_instrument || {}).map(([instrument_id, value]) => ({
    instrument_id,
    ...(value as JsonRecord),
  }));
  return (
    <div className="page-stack">
      <PageState loading={resource.loading} error={resource.error} />
      <div className="metric-grid">
        <Metric label="System" value={data.status || "unknown"} tone={data.status === "ok" ? "green" : "warn"} />
        <Metric label="PostgreSQL" value={data.database?.status || "unknown"} tone={data.database?.status === "ok" ? "green" : "red"} />
        <Metric label="Redis" value={data.redis?.status || "unknown"} tone={data.redis?.status === "ok" ? "green" : "warn"} />
        <Metric label="Migration" value={data.migration?.version || data.migration?.id || "none"} />
        <Metric label="Persistence backlog" value={backlogs.persistence} />
        <Metric label="Backfill backlog" value={backlogs.backfill} />
        <Metric label="Delivery DLQ" value={backlogs.dlq} tone={backlogs.dlq ? "red" : "green"} />
        <Metric label="Open anomalies" value={data.anomaly_count} tone={data.anomaly_count ? "warn" : "green"} />
      </div>
      <div className="split-grid">
        <Panel title="Service plane" action={<button className="button ghost small" onClick={() => void resource.reload()}>Refresh</button>}>
          <dl className="detail-list">
            <div><dt>WebSocket fan-out</dt><dd><StatusBadge value={data.websocket?.status} /></dd></div>
            <div><dt>Background refresh</dt><dd><StatusBadge value={data.background_refresh?.status} /></dd></div>
            <div><dt>Telegram sources</dt><dd><StatusBadge value={data.telegram?.status} /></dd></div>
            <div><dt>Provider states</dt><dd>{formatValue(data.provider_health || {})}</dd></div>
          </dl>
        </Panel>
        <Panel title="Estate counts">
          <div className="mini-metrics">
            <Metric label="Users" value={counts.users} />
            <Metric label="Support queue" value={counts.open_support_tickets} />
            <Metric label="Providers" value={counts.enabled_providers} />
            <Metric label="DLQ" value={counts.delivery_dlq} />
          </div>
        </Panel>
      </div>
      <Panel title="Latest canonical state">
        <DataTable rows={lastRows} rowKey="instrument_id" columns={[
          { key: "instrument_id", label: "Instrument" },
          { key: "status", label: "State", render: (row) => <StatusBadge value={row.status} /> },
          { key: "canonical_at", label: "Canonical time" },
          { key: "is_persisted", label: "Persisted" },
        ]} />
      </Panel>
    </div>
  );
}

export function UsersPage({ onDanger, refreshKey }: PageProps) {
  const [draftSearch, setDraftSearch] = useState("");
  const [search, setSearch] = useState("");
  const resource = useResource<JsonRecord>(`/users?search=${encodeURIComponent(search)}&limit=100&refresh=${refreshKey}`, { items: [] });
  const users: JsonRecord[] = resource.data.items || [];

  function userState(row: JsonRecord) {
    const next = !row.is_active;
    const word = next ? "ENABLE" : "DISABLE";
    onDanger({
      title: `${next ? "Enable" : "Disable"} ${row.username}`,
      expected: `${word} USER ${row.id}`,
      impact: next
        ? "Account access is restored. Existing revoked sessions remain closed."
        : "All administrator sessions close and the account is blocked until enabled again.",
      execute: async (confirmation) => {
        await adminApi.patch(`/users/${row.id}/state`, {
          is_active: next,
          reason: next ? "Account restored after administrator review" : "Account disabled after administrator review",
          confirmation,
        });
      },
    });
  }

  function forcePassword(row: JsonRecord) {
    onDanger({
      title: `Force password change for ${row.username}`,
      expected: `FORCE PASSWORD CHANGE ${row.id}`,
      impact: "The user must replace the password at the next enforced authentication step.",
      execute: async (confirmation) => {
        await adminApi.post(`/users/${row.id}/force-password-change`, { confirmation });
      },
    });
  }

  function closeSessions(row: JsonRecord) {
    onDanger({
      title: `Close sessions for ${row.username}`,
      expected: `CLOSE USER SESSIONS ${row.id}`,
      impact: "All tracked sessions are revoked. The user must sign in again.",
      execute: async (confirmation) => {
        await adminApi.post(`/users/${row.id}/sessions/close`, { confirmation });
      },
    });
  }

  return (
    <div className="page-stack">
      <Panel title="User directory" action={<form className="inline-form" onSubmit={(event) => { event.preventDefault(); setSearch(draftSearch); }}><input placeholder="Search user, email, name" value={draftSearch} onChange={(event) => setDraftSearch(event.target.value)} /><button className="button secondary small">Search</button></form>}>
        <PageState loading={resource.loading} error={resource.error} />
        <DataTable rows={users} columns={[
          { key: "username", label: "Account", render: (row) => <div className="primary-cell"><strong>{row.full_name}</strong><small>{row.username} · {row.email}</small></div> },
          { key: "is_active", label: "State", render: (row) => <StatusBadge value={row.is_active ? "active" : "disabled"} /> },
          { key: "must_change_password", label: "Password", render: (row) => row.must_change_password ? <StatusBadge value="change required" /> : "Current" },
          { key: "last_login_at", label: "Last login" },
          { key: "actions", label: "Actions", render: (row) => <div className="row-actions"><button className="link-button" onClick={() => userState(row)}>{row.is_active ? "Disable" : "Enable"}</button><button className="link-button" onClick={() => forcePassword(row)}>Force password</button><button className="link-button" onClick={() => closeSessions(row)}>Close sessions</button></div> },
        ]} />
      </Panel>
    </div>
  );
}

export function RolesPage({ onDanger, refreshKey }: PageProps) {
  const roles = useResource<JsonRecord>(`/roles?refresh=${refreshKey}`, { items: [] });
  const admins = useResource<JsonRecord>(`/administrators?refresh=${refreshKey}`, { items: [] });
  const [userId, setUserId] = useState("");
  const [roleName, setRoleName] = useState("viewer");

  function assign(event: React.FormEvent) {
    event.preventDefault();
    const target = Number(userId);
    if (!Number.isInteger(target) || target < 1) return;
    onDanger({
      title: `Set administrator role for user ${target}`,
      expected: `SET ADMIN ROLES ${target}`,
      impact: `This replaces current administrator assignments with ${roleName}. Backend permissions apply at once.`,
      execute: async (confirmation) => {
        await adminApi.put(`/administrators/${target}/roles`, { roles: [roleName], confirmation });
      },
    });
  }

  return (
    <div className="page-stack">
      <Panel title="Assign administrative access">
        <form className="settings-form" onSubmit={assign}>
          <label>User ID<input inputMode="numeric" value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="Existing user ID" /></label>
          <label>Role<select value={roleName} onChange={(event) => setRoleName(event.target.value)}>{(roles.data.items || []).map((role: JsonRecord) => <option key={role.name} value={role.name}>{role.name}</option>)}</select></label>
          <button className="button primary">Review role change</button>
        </form>
      </Panel>
      <Panel title="Administrators">
        <PageState loading={admins.loading} error={admins.error} />
        <DataTable rows={admins.data.items || []} columns={[
          { key: "username", label: "Administrator", render: (row) => <div className="primary-cell"><strong>{row.full_name}</strong><small>{row.username} · user {row.id}</small></div> },
          { key: "roles", label: "Roles", render: (row) => (row.roles || []).map((role: string) => <StatusBadge key={role} value={role} />) },
          { key: "is_active", label: "Account", render: (row) => <StatusBadge value={row.is_active ? "active" : "disabled"} /> },
          { key: "last_login_at", label: "Last login" },
        ]} />
      </Panel>
      <Panel title="Role permission map">
        <PageState loading={roles.loading} error={roles.error} />
        <div className="role-grid">{(roles.data.items || []).map((role: JsonRecord) => <article className="role-card" key={role.name}><div><h3>{role.name}</h3><StatusBadge value={role.is_active ? "active" : "disabled"} /></div><p>{role.description}</p><ul>{(role.permissions || []).map((permission: string) => <li key={permission}>{permission}</li>)}</ul></article>)}</div>
      </Panel>
    </div>
  );
}

export function SupportPage({ refreshKey }: PageProps) {
  const tickets = useResource<JsonRecord>(`/support/tickets?limit=100&refresh=${refreshKey}`, { items: [] });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<JsonRecord | null>(null);
  const [detailError, setDetailError] = useState("");
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");

  async function loadDetail(id: number) {
    setSelectedId(id);
    setDetailError("");
    try {
      setDetail(await adminApi.get(`/support/tickets/${id}`));
    } catch (reason) {
      setDetailError(humanError(reason));
    }
  }

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [refreshKey]);

  async function sendReply(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedId || !reply.trim()) return;
    await adminApi.post(`/support/tickets/${selectedId}/reply`, { content: reply });
    setReply("");
    await loadDetail(selectedId);
    await tickets.reload();
  }

  async function addNote(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedId || !note.trim()) return;
    await adminApi.post(`/support/tickets/${selectedId}/internal-notes`, { content: note });
    setNote("");
    await loadDetail(selectedId);
  }

  async function changeTicket(field: "status" | "priority", value: string) {
    if (!selectedId) return;
    await adminApi.patch(`/support/tickets/${selectedId}`, { [field]: value });
    await loadDetail(selectedId);
    await tickets.reload();
  }

  return (
    <div className="support-layout">
      <Panel title="Ticket queue" className="ticket-list-panel">
        <PageState loading={tickets.loading} error={tickets.error} />
        <div className="ticket-list">{(tickets.data.items || []).map((ticket: JsonRecord) => <button key={ticket.id} className={selectedId === ticket.id ? "active" : ""} onClick={() => void loadDetail(ticket.id)}><div><strong>{ticket.subject}</strong><StatusBadge value={ticket.priority} /></div><span>{ticket.user?.full_name} · {ticket.user?.email}</span><small><StatusBadge value={ticket.status} /> {formatValue(ticket.updated_at)}</small></button>)}</div>
      </Panel>
      <Panel title={detail?.ticket ? `Ticket #${detail.ticket.id}` : "Conversation"} className="conversation-panel">
        {detailError && <div className="error-banner">{detailError}</div>}
        {!detail?.ticket ? <EmptyState text="Select a ticket to open its full conversation" /> : <>
          <div className="ticket-toolbar">
            <div><strong>{detail.ticket.subject}</strong><small>{detail.ticket.user.full_name} · {detail.ticket.user.email}</small></div>
            <label>Status<select value={detail.ticket.status} onChange={(event) => void changeTicket("status", event.target.value)}><option>open</option><option>in_progress</option><option>waiting_for_user</option><option>resolved</option><option>closed</option></select></label>
            <label>Priority<select value={detail.ticket.priority} onChange={(event) => void changeTicket("priority", event.target.value)}><option>low</option><option>normal</option><option>high</option><option>urgent</option></select></label>
          </div>
          <div className="conversation">{(detail.messages || []).map((message: JsonRecord) => <article key={message.id} className={`message message-${message.from}`}><header>{message.from === "admin" ? "Administrator" : "User"}<time>{formatValue(message.created_at)}</time></header><p>{message.content}</p></article>)}</div>
          <form className="composer" onSubmit={sendReply}><textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Reply visible to the user" rows={3} /><button className="button primary">Send reply</button></form>
          <div className="internal-notes"><h3>Internal notes</h3>{(detail.internal_notes || []).map((item: JsonRecord) => <article key={item.id}><strong>{item.admin?.full_name || "Former administrator"}</strong><p>{item.content}</p><small>{formatValue(item.created_at)}</small></article>)}<form className="composer compact" onSubmit={addNote}><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Private note. Users never see this." rows={2} /><button className="button secondary">Add note</button></form></div>
        </>}
      </Panel>
    </div>
  );
}

export function ProvidersPage({ onDanger, refreshKey }: PageProps) {
  const providers = useResource<JsonRecord>(`/providers?refresh=${refreshKey}`, { items: [] });
  const telegram = useResource<JsonRecord>(`/telegram/sources?refresh=${refreshKey}`, { items: [], recent_rejections: [] });
  const [error, setError] = useState("");
  const [channelId, setChannelId] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceRole, setSourceRole] = useState("verifier");
  const [sourceInstruments, setSourceInstruments] = useState("USDT_TOMAN");
  const [parserType, setParserType] = useState("strict_generic");

  async function stageProviderToggle(row: JsonRecord) {
    setError("");
    try {
      const result = await adminApi.post<JsonRecord>(`/providers/${row.provider_id}/drafts`, { enabled: !row.enabled });
      onDanger({
        title: `${row.enabled ? "Disable" : "Enable"} provider ${row.provider_id}`,
        expected: result.confirmation,
        impact: (result.impact?.warnings || []).join(". ") || "The saved runtime provider policy changes without exposing or editing credentials.",
        execute: async (confirmation) => {
          await adminApi.post(`/providers/drafts/${result.draft_id}/apply`, { confirmation });
        },
      });
    } catch (reason) {
      setError(humanError(reason));
    }
  }

  function toggleTelegram(row: JsonRecord) {
    const sourceId = row.source_id;
    onDanger({
      title: `${row.enabled ? "Disable" : "Enable"} Telegram source ${sourceId}`,
      expected: `UPDATE TELEGRAM SOURCE ${sourceId}`,
      impact: row.enabled && row.role === "fallback"
        ? "This removes a configured fallback path. Canonical pricing must use remaining eligible sources."
        : "This changes source eligibility for stored Telegram messages.",
      execute: async (confirmation) => {
        await adminApi.patch(`/telegram/sources/${sourceId}`, { enabled: !row.enabled, confirmation });
      },
    });
  }

  function createTelegram(event: React.FormEvent) {
    event.preventDefault();
    const cleanChannel = channelId.trim();
    const instruments = sourceInstruments.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean);
    if (!cleanChannel || !sourceName.trim() || !instruments.length) return;
    onDanger({
      title: `Create Telegram source ${cleanChannel}`,
      expected: `CREATE TELEGRAM SOURCE ${cleanChannel}`,
      impact: "Only future messages from this explicit source can enter strict parsing and verification. No session credential is stored here.",
      execute: async (confirmation) => {
        await adminApi.post("/telegram/sources", {
          channel_id: cleanChannel,
          display_name: sourceName.trim(),
          source_type: "channel",
          allowed_instruments: instruments,
          role: sourceRole,
          trust_score: 0.5,
          minimum_confidence: 0.8,
          maximum_message_age_seconds: 300,
          maximum_deviation_percent: 3,
          requires_multiple_sources: sourceRole === "fallback",
          parser_type: parserType.trim(),
          parser_version: "1.0.0",
          enabled: true,
          confirmation,
        });
      },
    });
  }

  return (
    <div className="page-stack">
      {error && <div className="error-banner">{error}</div>}
      <Panel title="Pricing providers" action={<button className="button ghost small" onClick={() => void providers.reload()}>Refresh</button>}>
        <PageState loading={providers.loading} error={providers.error} />
        <DataTable rows={providers.data.items || []} rowKey="provider_id" columns={[
          { key: "provider_id", label: "Provider", render: (row) => <div className="primary-cell"><strong>{row.display_name || row.name || row.provider_id}</strong><small>{row.asset ? `${row.asset} · ${row.region}` : row.provider_id}</small></div> },
          { key: "enabled", label: "State", render: (row) => <StatusBadge value={row.enabled ? "enabled" : "disabled"} /> },
          { key: "role", label: "Role", render: (row) => <StatusBadge value={row.role} /> },
          { key: "health_status", label: "Health", render: (row) => <StatusBadge value={row.health_status} /> },
          { key: "trust_score", label: "Trust" },
          { key: "minimum_interval_seconds", label: "Min interval" },
          { key: "operational_ttl_seconds", label: "TTL" },
          { key: "credential_status", label: "Credential", render: (row) => row.credential_status?.configured ? `Configured ${row.credential_status.masked_suffix || ""}` : "Not required / unset" },
          { key: "actions", label: "Actions", render: (row) => <button className="link-button" onClick={() => void stageProviderToggle(row)}>{row.enabled ? "Stage disable" : "Stage enable"}</button> },
        ]} />
      </Panel>
      <Panel title="Telegram verifier and fallback sources">
        <form className="settings-form source-form" onSubmit={createTelegram}>
          <label>Channel ID<input value={channelId} onChange={(event) => setChannelId(event.target.value)} placeholder="-1001234567890" /></label>
          <label>Display name<input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="Verified market channel" /></label>
          <label>Role<select value={sourceRole} onChange={(event) => setSourceRole(event.target.value)}><option value="compare">compare</option><option value="verifier">verifier</option><option value="fallback">fallback</option></select></label>
          <label>Allowed instruments<input value={sourceInstruments} onChange={(event) => setSourceInstruments(event.target.value)} placeholder="USDT_TOMAN,BTC_TOMAN" /></label>
          <label>Parser<input value={parserType} onChange={(event) => setParserType(event.target.value)} placeholder="strict_generic" /></label>
          <button className="button primary">Review new source</button>
        </form>
        <p className="policy-copy">Source session strings stay in environment secret storage. This form cannot read or write them.</p>
        <PageState loading={telegram.loading} error={telegram.error} />
        <DataTable rows={telegram.data.items || []} rowKey="source_id" columns={[
          { key: "display_name", label: "Source", render: (row) => <div className="primary-cell"><strong>{row.display_name || row.username || row.channel_id}</strong><small>{row.channel_id}</small></div> },
          { key: "enabled", label: "State", render: (row) => <StatusBadge value={row.enabled ? "enabled" : "disabled"} /> },
          { key: "role", label: "Role" },
          { key: "trust_score", label: "Trust" },
          { key: "minimum_confidence", label: "Min confidence" },
          { key: "parser_version", label: "Parser" },
          { key: "last_accepted_message_at", label: "Last accepted" },
          { key: "actions", label: "Actions", render: (row) => <button className="link-button" onClick={() => toggleTelegram(row)}>{row.enabled ? "Disable" : "Enable"}</button> },
        ]} />
      </Panel>
      <Panel title="Recent Telegram rejections">
        <DataTable rows={telegram.data.recent_rejections || []} columns={[
          { key: "source_id", label: "Source" },
          { key: "message_id", label: "Message" },
          { key: "validation_status", label: "State", render: (row) => <StatusBadge value={row.validation_status} /> },
          { key: "rejection_reason", label: "Reason" },
          { key: "created_at", label: "Time" },
        ]} />
      </Panel>
    </div>
  );
}

export function PricingPage({ refreshKey }: PageProps) {
  const instruments = useResource<JsonRecord>(`/pricing/instruments?refresh=${refreshKey}`, { items: [] });
  const anomalies = useResource<JsonRecord>(`/pricing/anomalies?refresh=${refreshKey}`, { items: [] });
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [message, setMessage] = useState("");

  async function openInstrument(instrumentId: string) {
    try {
      setSelected(await adminApi.get(`/pricing/instruments/${instrumentId}?history_limit=100`));
      setMessage("");
    } catch (reason) {
      setMessage(humanError(reason));
    }
  }

  async function refresh(instrumentId: string) {
    try {
      const result = await adminApi.post<JsonRecord>(`/pricing/instruments/${instrumentId}/refresh`, {
        reason: "Budget-controlled refresh requested from operations console",
      });
      setMessage(`Refresh job ${result.job_id} queued`);
    } catch (reason) {
      setMessage(humanError(reason));
    }
  }

  async function review(anomalyId: string, reviewStatus: string) {
    try {
      await adminApi.post(`/pricing/anomalies/${anomalyId}/review`, { status: reviewStatus, note: "Reviewed in operations console" });
      await anomalies.reload();
    } catch (reason) {
      setMessage(humanError(reason));
    }
  }

  return (
    <div className="page-stack">
      {message && <div className="info-banner">{message}</div>}
      <Panel title="Instrument state">
        <PageState loading={instruments.loading} error={instruments.error} />
        <DataTable rows={instruments.data.items || []} rowKey="instrument_id" columns={[
          { key: "instrument_id", label: "Instrument", render: (row) => <div className="primary-cell"><strong>{row.instrument_id || row.id}</strong><small>{row.market} · {row.region}</small></div> },
          { key: "enabled", label: "Enabled", render: (row) => <StatusBadge value={row.enabled ? "enabled" : "disabled"} /> },
          { key: "price", label: "Canonical", render: (row) => formatValue(row.latest_canonical?.price) },
          { key: "status", label: "State", render: (row) => <StatusBadge value={row.latest_canonical?.status || row.status} /> },
          { key: "canonical_at", label: "Updated", render: (row) => formatValue(row.latest_canonical?.canonical_at) },
          { key: "actions", label: "Actions", render: (row) => <div className="row-actions"><button className="link-button" onClick={() => void openInstrument(row.instrument_id || row.id)}>Inspect</button><button className="link-button" onClick={() => void refresh(row.instrument_id || row.id)}>Request refresh</button></div> },
        ]} />
      </Panel>
      {selected && <Panel title={`Source review · ${selected.instrument?.instrument_id || selected.instrument?.id}`} action={<button className="icon-button" onClick={() => setSelected(null)}>×</button>}>
        <div className="split-grid">
          <div><h3>Latest canonical</h3><pre className="record-view">{JSON.stringify(selected.latest_canonical, null, 2)}</pre></div>
          <div><h3>Recent sources</h3><DataTable rows={selected.source_quotes || []} columns={[
            { key: "provider_id", label: "Provider" },
            { key: "price", label: "Price" },
            { key: "validation_status", label: "Validation", render: (row) => <StatusBadge value={row.validation_status} /> },
            { key: "is_suspicious", label: "Suspicious" },
            { key: "observed_at", label: "Observed" },
          ]} /></div>
        </div>
      </Panel>}
      <Panel title="Anomaly review queue">
        <PageState loading={anomalies.loading} error={anomalies.error} />
        <DataTable rows={anomalies.data.items || []} columns={[
          { key: "instrument_id", label: "Instrument" },
          { key: "candidate_price", label: "Candidate" },
          { key: "previous_price", label: "Accepted" },
          { key: "deviation_percent", label: "Difference" },
          { key: "status", label: "Decision", render: (row) => <StatusBadge value={row.status} /> },
          { key: "admin_review", label: "Review", render: (row) => row.admin_review ? <StatusBadge value={row.admin_review.status} /> : "Pending" },
          { key: "actions", label: "Actions", render: (row) => <div className="row-actions"><button className="link-button" onClick={() => void review(String(row.id), "reviewed")}>Mark reviewed</button><button className="link-button" onClick={() => void review(String(row.id), "dismissed")}>Dismiss</button></div> },
        ]} />
      </Panel>
    </div>
  );
}

export function JobsPage({ onDanger, refreshKey }: PageProps) {
  const jobs = useResource<JsonRecord>(`/jobs?limit=100&refresh=${refreshKey}`, { admin_jobs: [], backfill_jobs: [], delivery_jobs: [] });
  const [message, setMessage] = useState("");

  async function retryAdmin(id: number) {
    try {
      await adminApi.post(`/jobs/${id}/retry`, {});
      await jobs.reload();
    } catch (reason) {
      setMessage(humanError(reason));
    }
  }

  async function retryDelivery(id: string) {
    try {
      await adminApi.post(`/jobs/delivery/${id}/retry`, {});
      await jobs.reload();
    } catch (reason) {
      setMessage(humanError(reason));
    }
  }

  function cancelDelivery(row: JsonRecord) {
    onDanger({
      title: `Cancel delivery job ${row.id}`,
      expected: `CANCEL DELIVERY ${row.id}`,
      impact: "Pending retries stop for this channel delivery. The durable record remains for audit.",
      execute: async (confirmation) => {
        await adminApi.post(`/jobs/delivery/${row.id}/cancel`, { confirmation });
      },
    });
  }

  const deliveryRows = jobs.data.delivery_jobs || [];
  return (
    <div className="page-stack">
      {message && <div className="info-banner">{message}</div>}
      <Panel title="Operational requests" action={<button className="button ghost small" onClick={() => void jobs.reload()}>Refresh</button>}>
        <PageState loading={jobs.loading} error={jobs.error} />
        <DataTable rows={jobs.data.admin_jobs || []} columns={[
          { key: "job_type", label: "Job" },
          { key: "resource_id", label: "Resource" },
          { key: "status", label: "State", render: (row) => <StatusBadge value={row.status} /> },
          { key: "attempt_count", label: "Attempts" },
          { key: "last_error", label: "Last error" },
          { key: "created_at", label: "Created" },
          { key: "actions", label: "Actions", render: (row) => ["failed", "dead", "cancelled"].includes(row.status) ? <button className="link-button" onClick={() => void retryAdmin(row.id)}>Retry</button> : "—" },
        ]} />
      </Panel>
      <Panel title="Alert delivery and dead letters">
        <DataTable rows={deliveryRows} columns={[
          { key: "id", label: "ID" },
          { key: "channel", label: "Channel" },
          { key: "status", label: "State", render: (row) => <StatusBadge value={row.status} /> },
          { key: "attempt_count", label: "Attempts" },
          { key: "next_retry_at", label: "Next retry" },
          { key: "last_error", label: "Sanitized error" },
          { key: "actions", label: "Actions", render: (row) => <div className="row-actions">{["failed", "dead", "retrying"].includes(row.status) && <button className="link-button" onClick={() => void retryDelivery(String(row.id))}>Retry</button>}{!["delivered", "cancelled"].includes(row.status) && <button className="link-button danger-text" onClick={() => cancelDelivery(row)}>Cancel</button>}</div> },
        ]} />
      </Panel>
      <Panel title="Backfill jobs">
        <DataTable rows={jobs.data.backfill_jobs || []} columns={[
          { key: "instrument_id", label: "Instrument" },
          { key: "provider_id", label: "Provider" },
          { key: "status", label: "State", render: (row) => <StatusBadge value={row.status} /> },
          { key: "range_start", label: "From" },
          { key: "range_end", label: "To" },
          { key: "attempt_count", label: "Attempts" },
        ]} />
      </Panel>
    </div>
  );
}

export function SettingsPage({ onDanger, refreshKey }: PageProps) {
  const settings = useResource<JsonRecord>(`/settings?refresh=${refreshKey}`, { feature_flags: [], operational_settings: [], environment: {} });
  const [settingKey, setSettingKey] = useState("comparison_visible");
  const [scope, setScope] = useState("global");
  const [rawValue, setRawValue] = useState("true");
  const [message, setMessage] = useState("");
  const dangerousKeys = new Set(["anomaly_threshold_percent", "canonical_expiry_seconds", "provider_budget_requests_per_hour"]);
  const booleanKeys = new Set(["comparison_visible", "derived_fallback_enabled", "backfill_enabled", "telegram_source_enabled"]);

  async function writeSetting(confirmation?: string) {
    const value = booleanKeys.has(settingKey) ? rawValue === "true" : Number(rawValue);
    await adminApi.put("/settings/operational", { key: settingKey, scope_id: scope, value, confirmation });
  }

  function submitSetting(event: React.FormEvent) {
    event.preventDefault();
    if (dangerousKeys.has(settingKey)) {
      const expected = `CHANGE SETTING ${settingKey}:${scope}`;
      onDanger({
        title: `Change ${settingKey}`,
        expected,
        impact: "This changes live pricing safety or request budget policy. The previous version remains in audit history.",
        execute: async (confirmation) => writeSetting(confirmation),
      });
      return;
    }
    writeSetting().then(() => settings.reload()).catch((reason) => setMessage(humanError(reason)));
  }

  function toggleFlag(flag: JsonRecord) {
    const next = !flag.enabled;
    if (flag.key === "admin_frontend_enabled" && !next) {
      onDanger({
        title: "Disable admin frontend flag",
        expected: "DISABLE ADMIN FRONTEND",
        impact: "The database runtime flag turns off. Environment and deployment policy remain authoritative.",
        execute: async (confirmation) => {
          await adminApi.patch(`/settings/feature-flags/${flag.key}`, { enabled: next, confirmation });
        },
      });
      return;
    }
    adminApi.patch(`/settings/feature-flags/${flag.key}`, { enabled: next }).then(() => settings.reload()).catch((reason) => setMessage(humanError(reason)));
  }

  return (
    <div className="page-stack">
      {message && <div className="info-banner">{message}</div>}
      <Panel title="Runtime feature flags">
        <PageState loading={settings.loading} error={settings.error} />
        <div className="flag-grid">{(settings.data.feature_flags || []).map((flag: JsonRecord) => <article key={flag.key}><div><strong>{flag.key}</strong><StatusBadge value={flag.enabled ? "enabled" : "disabled"} /></div><p>{flag.description}</p><button className="button secondary small" onClick={() => toggleFlag(flag)}>{flag.enabled ? "Disable" : "Enable"}</button></article>)}</div>
      </Panel>
      <Panel title="Safe operational setting">
        <form className="settings-form" onSubmit={submitSetting}>
          <label>Setting<select value={settingKey} onChange={(event) => { setSettingKey(event.target.value); setRawValue(booleanKeys.has(event.target.value) ? "true" : "1"); }}><option>comparison_visible</option><option>derived_fallback_enabled</option><option>backfill_enabled</option><option>telegram_source_enabled</option><option>anomaly_threshold_percent</option><option>canonical_expiry_seconds</option><option>provider_budget_requests_per_hour</option></select></label>
          <label>Scope<input value={scope} onChange={(event) => setScope(event.target.value)} placeholder="global or instrument/provider ID" /></label>
          <label>Value{booleanKeys.has(settingKey) ? <select value={rawValue} onChange={(event) => setRawValue(event.target.value)}><option value="true">true</option><option value="false">false</option></select> : <input type="number" step="any" value={rawValue} onChange={(event) => setRawValue(event.target.value)} />}</label>
          <button className="button primary">Save setting</button>
        </form>
        <p className="policy-copy">Credentials and arbitrary JSON are not editable here.</p>
      </Panel>
      <Panel title="Stored operational overrides">
        <DataTable rows={settings.data.operational_settings || []} rowKey="key" columns={[
          { key: "key", label: "Setting" },
          { key: "scope_id", label: "Scope" },
          { key: "value", label: "Value" },
          { key: "version", label: "Version" },
          { key: "updated_at", label: "Updated" },
        ]} />
      </Panel>
      <Panel title="Environment policy">
        <dl className="detail-list">{Object.entries(settings.data.environment || {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatValue(value)}</dd></div>)}</dl>
      </Panel>
    </div>
  );
}

export function AuditPage({ refreshKey }: PageProps) {
  const [filter, setFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("");
  const query = activeFilter ? `&action=${encodeURIComponent(activeFilter)}` : "";
  const audit = useResource<JsonRecord>(`/audit?limit=200${query}&refresh=${refreshKey}`, { items: [] });
  return (
    <div className="page-stack">
      <Panel title="Immutable audit trail" action={<form className="inline-form" onSubmit={(event) => { event.preventDefault(); setActiveFilter(filter); }}><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Exact action filter" /><button className="button secondary small">Filter</button></form>}>
        <PageState loading={audit.loading} error={audit.error} />
        <DataTable rows={audit.data.items || []} columns={[
          { key: "created_at", label: "Time" },
          { key: "actor_admin_id", label: "Actor" },
          { key: "action", label: "Action" },
          { key: "resource_type", label: "Resource", render: (row) => <div className="primary-cell"><strong>{row.resource_type}</strong><small>{row.resource_id}</small></div> },
          { key: "result", label: "Result", render: (row) => <StatusBadge value={row.result} /> },
          { key: "ip_address", label: "IP" },
          { key: "request_id", label: "Request" },
          { key: "detail", label: "Detail" },
        ]} />
      </Panel>
    </div>
  );
}
