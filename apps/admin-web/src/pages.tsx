import { useEffect, useRef, useState } from "react";

import { adminApi } from "./api";
import type { DangerousAction, JsonRecord } from "./types";
import {
  DataTable,
  PageState,
  Panel,
  StatusBadge,
  formatValue,
  useResource,
  useOperation,
  Pagination,
  RecordDetails,
} from "./ui";

interface PageProps {
  onDanger: (action: DangerousAction) => void;
  refreshKey: number;
  permissions: string[];
}

function Metric({
  label,
  value,
  tone = "gold",
}: {
  label: string;
  value: unknown;
  tone?: string;
}) {
  return (
    <article className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{formatValue(value)}</strong>
    </article>
  );
}

export function DashboardPage({ refreshKey }: PageProps) {
  const resource = useResource<JsonRecord>(
    `/dashboard?refresh=${refreshKey}`,
    {},
  );
  const data = resource.data;
  const backlogs = data.backlogs || {};
  const counts = data.counts || {};
  const lastRows = Object.entries(
    data.background_refresh?.last_by_instrument || {},
  ).map(([instrument_id, value]) => ({
    instrument_id,
    ...(value as JsonRecord),
  }));
  return (
    <div className="page-stack">
      <PageState loading={resource.loading} error={resource.error} />
      <div className="metric-grid">
        <Metric
          label="System"
          value={data.status || "unknown"}
          tone={data.status === "ok" ? "green" : "warn"}
        />
        <Metric
          label="PostgreSQL"
          value={data.database?.status || "unknown"}
          tone={data.database?.status === "ok" ? "green" : "red"}
        />
        <Metric
          label="Redis"
          value={data.redis?.status || "unknown"}
          tone={data.redis?.status === "ok" ? "green" : "warn"}
        />
        <Metric
          label="Migration"
          value={data.migration?.version || data.migration?.id || "none"}
        />
        <Metric label="Persistence backlog" value={backlogs.persistence} />
        <Metric label="Backfill backlog" value={backlogs.backfill} />
        <Metric
          label="Delivery DLQ"
          value={backlogs.dlq}
          tone={backlogs.dlq ? "red" : "green"}
        />
        <Metric
          label="Open anomalies"
          value={data.anomaly_count}
          tone={data.anomaly_count ? "warn" : "green"}
        />
      </div>
      <div className="split-grid">
        <Panel
          title="Service plane"
          action={
            <button
              className="button ghost small"
              onClick={() => void resource.reload()}
            >
              Refresh
            </button>
          }
        >
          <dl className="detail-list">
            <div>
              <dt>WebSocket fan-out</dt>
              <dd>
                <StatusBadge value={data.websocket?.status} />
              </dd>
            </div>
            <div>
              <dt>Background refresh</dt>
              <dd>
                <StatusBadge value={data.background_refresh?.status} />
              </dd>
            </div>
            <div>
              <dt>Telegram sources</dt>
              <dd>
                <StatusBadge value={data.telegram?.status} />
              </dd>
            </div>
            <div>
              <dt>Provider states</dt>
              <dd>{formatValue(data.provider_health || {})}</dd>
            </div>
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
        <DataTable
          rows={lastRows}
          rowKey="instrument_id"
          columns={[
            { key: "instrument_id", label: "Instrument" },
            {
              key: "status",
              label: "State",
              render: (row) => <StatusBadge value={row.status} />,
            },
            { key: "canonical_at", label: "Canonical time" },
            { key: "is_persisted", label: "Persisted" },
          ]}
        />
      </Panel>
    </div>
  );
}

const PAGE_SIZE = 50;
const can = (props: PageProps, key: string) =>
  props.permissions.includes(`admin.${key}`);
const query = (values: Record<string, string | number | boolean | undefined>) =>
  new URLSearchParams(
    Object.entries(values)
      .filter(([, value]) => value !== undefined && value !== "")
      .map(([key, value]) => [key, String(value)]),
  ).toString();
const columns = (...keys: string[]) =>
  keys.map((key) => ({ key, label: key.replaceAll("_", " ") }));

function ActionError({ error }: { error: string }) {
  return error ? (
    <div className="error-banner" role="alert">
      {error}
    </div>
  ) : null;
}
function Filters({ children }: { children: React.ReactNode }) {
  return <div className="filter-grid">{children}</div>;
}
function DetailTables({
  value,
  fields,
}: {
  value: JsonRecord;
  fields: Record<string, string[]>;
}) {
  return (
    <>
      {Object.entries(fields).map(([key, keys]) => (
        <Panel key={key} title={key.replaceAll("_", " ")}>
          <DataTable rows={value[key] || []} columns={columns(...keys)} />
        </Panel>
      ))}
    </>
  );
}

export function UsersPage(props: PageProps) {
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const resource = useResource<JsonRecord>(
    `/users?${query({ search, active, limit: PAGE_SIZE, offset, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const detail = useResource<JsonRecord>(
    selected ? `/users/${selected}` : "/users?limit=1",
    {},
  );
  const [reason, setReason] = useState("");
  const danger = (user: JsonRecord, action: string) => {
    const expected =
      action === "state"
        ? `${user.is_active ? "DISABLE" : "ENABLE"} USER ${user.id}`
        : action === "password"
          ? `FORCE PASSWORD CHANGE ${user.id}`
          : `CLOSE USER SESSIONS ${user.id}`;
    props.onDanger({
      title: expected,
      expected,
      impact:
        action === "state"
          ? "Disable closes both session types. The last active super administrator stays protected."
          : "All affected sessions close. The user must sign in again.",
      execute: async (confirmation) => {
        if (action === "state")
          await adminApi.patch(`/users/${user.id}/state`, {
            is_active: !user.is_active,
            reason,
            confirmation,
          });
        else
          await adminApi.post(
            `/users/${user.id}/${action === "password" ? "force-password-change" : "sessions/close"}`,
            { confirmation },
          );
      },
    });
  };
  return (
    <div className="page-stack">
      <Filters>
        <label>
          Search
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          State
          <select
            value={active}
            onChange={(event) => {
              setActive(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            <option value="true">Active</option>
            <option value="false">Disabled</option>
          </select>
        </label>
        {can(props, "users.manage") && (
          <label>
            Change reason
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              minLength={3}
              maxLength={240}
            />
          </label>
        )}
      </Filters>
      <PageState loading={resource.loading} error={resource.error} />
      <Panel title="Users">
        <DataTable
          rows={resource.data.items}
          columns={[
            ...columns(
              "id",
              "username",
              "full_name",
              "email",
              "is_active",
              "must_change_password",
              "last_login_at",
            ),
            {
              key: "actions",
              label: "Actions",
              render: (user) => (
                <div className="row-actions">
                  <button
                    className="button ghost small"
                    onClick={() => setSelected(user.id)}
                  >
                    Details
                  </button>
                  {can(props, "users.manage") && (
                    <>
                      <button
                        className="button secondary small"
                        disabled={reason.trim().length < 3}
                        onClick={() => danger(user, "state")}
                      >
                        {user.is_active ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="button ghost small"
                        onClick={() => danger(user, "password")}
                      >
                        Force password change
                      </button>
                    </>
                  )}
                  {can(props, "sessions.manage") && (
                    <button
                      className="button danger small"
                      onClick={() => danger(user, "sessions")}
                    >
                      Close all sessions
                    </button>
                  )}
                </div>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={resource.data.total}
          onChange={setOffset}
          busy={resource.loading}
        />
      </Panel>
      {selected !== null && (
        <>
          <PageState loading={detail.loading} error={detail.error} />
          {!detail.loading && detail.data.user?.id === selected && (
            <>
              <Panel title="User details">
                <RecordDetails value={detail.data.user} />
              </Panel>
              <UserEvidence key={selected} userId={selected} {...props} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function UserEvidence({ userId, ...props }: PageProps & { userId: number }) {
  const [kind, setKind] = useState("user");
  const [offset, setOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const sessions = useResource<JsonRecord>(
    `/users/${userId}/sessions?${query({ kind, limit: PAGE_SIZE, offset, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const events = useResource<JsonRecord>(
    `/users/${userId}/security-history?${query({ limit: PAGE_SIZE, offset: eventOffset, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  return (
    <>
      <Panel title="All sessions">
        <label>
          Session type
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setOffset(0);
            }}
          >
            <option value="user">Public</option>
            <option value="admin">Administrator</option>
          </select>
        </label>
        <PageState loading={sessions.loading} error={sessions.error} />
        <DataTable
          rows={sessions.data.items}
          columns={[
            ...columns(
              "id",
              "created_at",
              "expires_at",
              "revoked_at",
              kind === "admin" ? "last_seen_at" : "last_used_at",
            ),
            {
              key: "close",
              label: "Close",
              render: (session) =>
                can(props, "sessions.manage") &&
                !session.revoked_at && (
                  <button
                    className="button danger small"
                    onClick={() =>
                      props.onDanger({
                        title: "Close one session",
                        expected: `CLOSE ${kind.toUpperCase()} SESSION ${session.id}`,
                        impact: "Only this credential is revoked.",
                        execute: async (confirmation) => {
                          await adminApi.post(
                            `/users/${userId}/sessions/${kind}/${session.id}/close`,
                            { confirmation },
                          );
                        },
                      })
                    }
                  >
                    Close
                  </button>
                ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={sessions.data.total}
          onChange={setOffset}
          busy={sessions.loading}
        />
      </Panel>
      <Panel title="All security events">
        <PageState loading={events.loading} error={events.error} />
        <DataTable
          rows={events.data.items}
          columns={columns(
            "id",
            "action",
            "result",
            "created_at",
            "ip_address",
          )}
        />
        <Pagination
          offset={eventOffset}
          limit={PAGE_SIZE}
          total={events.data.total}
          onChange={setEventOffset}
          busy={events.loading}
        />
      </Panel>
    </>
  );
}

export function RolesPage(props: PageProps) {
  const roles = useResource<JsonRecord>(`/roles?refresh=${props.refreshKey}`, {
    items: [],
  });
  const admins = useResource<JsonRecord>(
    `/administrators?refresh=${props.refreshKey}`,
    { items: [] },
  );
  const permissions = useResource<JsonRecord>("/permissions", { items: [] });
  const [search, setSearch] = useState("");
  const users = useResource<JsonRecord>(
    `/users?${query({ search, limit: 50 })}`,
    { items: [] },
  );
  const [target, setTarget] = useState("");
  const [wanted, setWanted] = useState<string[]>([]);
  const [editingRole, setEditingRole] = useState<JsonRecord | null>(null);
  const [roleName, setRoleName] = useState("");
  const [description, setDescription] = useState("");
  const [roleActive, setRoleActive] = useState(true);
  const [rolePermissions, setRolePermissions] = useState<string[]>([]);
  const toggle = (values: string[], value: string) =>
    values.includes(value)
      ? values.filter((item) => item !== value)
      : [...values, value];
  const edit = (role: JsonRecord | null) => {
    setEditingRole(role);
    setRoleName(role?.name || "");
    setDescription(role?.description || "");
    setRoleActive(role?.is_active ?? true);
    setRolePermissions(role?.permissions || []);
  };
  const assign = () =>
    props.onDanger({
      title: "Change administrator roles",
      expected: `SET ADMIN ROLES ${target}`,
      impact:
        "Selected roles replace all current roles. Empty selection revokes administrator access and closes sessions.",
      execute: async (confirmation) => {
        await adminApi.put(`/administrators/${target}/roles`, {
          roles: wanted,
          confirmation,
        });
      },
    });
  const saveRole = (event: React.FormEvent) => {
    event.preventDefault();
    const expected = editingRole
      ? `UPDATE ROLE ${editingRole.id}`
      : `CREATE ROLE ${roleName}`;
    props.onDanger({
      title: expected,
      expected,
      impact:
        "System roles cannot change here. Changing a custom role closes affected administrator sessions.",
      execute: async (confirmation) => {
        const body = {
          name: roleName,
          description,
          is_active: roleActive,
          permissions: rolePermissions,
          confirmation,
        };
        if (editingRole) await adminApi.put(`/roles/${editingRole.id}`, body);
        else await adminApi.post("/roles", body);
      },
    });
  };
  return (
    <div className="page-stack">
      <PageState
        loading={roles.loading || admins.loading}
        error={roles.error || admins.error}
      />
      <Panel title="Administrators">
        <DataTable
          rows={admins.data.items}
          columns={[
            ...columns("id", "username", "full_name", "roles", "is_active"),
            {
              key: "actions",
              label: "Actions",
              render: (admin) => (
                <div className="row-actions">
                  {can(props, "roles.manage") && (
                    <button
                      className="button ghost small"
                      onClick={() => {
                        setTarget(String(admin.id));
                        setWanted(admin.roles);
                      }}
                    >
                      Edit roles
                    </button>
                  )}
                  {can(props, "sessions.manage") && (
                    <button
                      className="button danger small"
                      onClick={() =>
                        props.onDanger({
                          title: "Close administrator sessions",
                          expected: `CLOSE ADMIN SESSIONS ${admin.id}`,
                          impact:
                            "Only administrator sessions close. Public sessions stay unchanged.",
                          execute: async (confirmation) => {
                            await adminApi.post(
                              `/administrators/${admin.id}/sessions/close`,
                              { confirmation },
                            );
                          },
                        })
                      }
                    >
                      Close admin sessions
                    </button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Panel>
      <Panel title="Role policy">
        <DataTable
          rows={roles.data.items}
          columns={[
            ...columns(
              "name",
              "description",
              "is_system",
              "is_active",
              "permissions",
            ),
            {
              key: "edit",
              label: "Edit",
              render: (role) =>
                !role.is_system &&
                can(props, "roles.manage") && (
                  <button
                    className="button ghost small"
                    onClick={() => edit(role)}
                  >
                    Edit custom role
                  </button>
                ),
            },
          ]}
        />
      </Panel>
      {can(props, "roles.manage") && (
        <>
          <Panel title="Assign roles">
            <Filters>
              <label>
                Find user
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <label>
                User
                <select
                  value={target}
                  onChange={(event) => {
                    setTarget(event.target.value);
                    setWanted(
                      admins.data.items.find(
                        (item: JsonRecord) =>
                          String(item.id) === event.target.value,
                      )?.roles || [],
                    );
                  }}
                >
                  <option value="">Choose user</option>
                  {users.data.items.map((item: JsonRecord) => (
                    <option value={item.id} key={item.id}>
                      {item.username} · {item.full_name} · #{item.id}
                    </option>
                  ))}
                </select>
              </label>
            </Filters>
            <div className="check-grid">
              {roles.data.items
                .filter((role: JsonRecord) => role.is_active)
                .map((role: JsonRecord) => (
                  <label className="check-label" key={role.name}>
                    <input
                      type="checkbox"
                      checked={wanted.includes(role.name)}
                      onChange={() => setWanted(toggle(wanted, role.name))}
                    />
                    {role.name}
                  </label>
                ))}
            </div>
            <button
              className="button primary"
              disabled={!target}
              onClick={assign}
            >
              Apply selected roles
            </button>
          </Panel>
          <Panel
            title={
              editingRole ? `Edit ${editingRole.name}` : "Create custom role"
            }
            action={
              <button className="button ghost small" onClick={() => edit(null)}>
                New role
              </button>
            }
          >
            <form onSubmit={saveRole} className="page-stack">
              <Filters>
                <label>
                  Name
                  <input
                    value={roleName}
                    pattern="[a-z][a-z0-9_]+"
                    minLength={3}
                    maxLength={64}
                    required
                    onChange={(event) => setRoleName(event.target.value)}
                  />
                </label>
                <label>
                  Description
                  <input
                    value={description}
                    maxLength={240}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={roleActive}
                    onChange={(event) => setRoleActive(event.target.checked)}
                  />
                  Active
                </label>
              </Filters>
              <div className="check-grid">
                {permissions.data.items
                  .filter((item: JsonRecord) =>
                    props.permissions.includes(item.key),
                  )
                  .map((item: JsonRecord) => (
                    <label className="check-label" key={item.key}>
                      <input
                        type="checkbox"
                        checked={rolePermissions.includes(item.key)}
                        onChange={() =>
                          setRolePermissions(toggle(rolePermissions, item.key))
                        }
                      />
                      {item.description}
                    </label>
                  ))}
              </div>
              <button className="button primary">Review role change</button>
            </form>
          </Panel>
        </>
      )}
    </div>
  );
}

export function SupportPage(props: PageProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [assignee, setAssignee] = useState("");
  const [offset, setOffset] = useState(0);
  const tickets = useResource<JsonRecord>(
    `/support/tickets?${query({ search, status, priority, assigned_admin_id: assignee, limit: PAGE_SIZE, offset, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const assignees = useResource<JsonRecord>("/support/assignees", {
    items: [],
  });
  const [selected, setSelected] = useState<number | null>(null);
  const detail = useResource<JsonRecord>(
    selected ? `/support/tickets/${selected}` : "/support/tickets?limit=1",
    {},
  );
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const operation = useOperation();
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const ready = !detail.loading && detail.data.ticket?.id === selected;
  const select = (id: number) => {
    setSelected(id);
    setText("");
    setNote("");
  };
  const change = (body: JsonRecord) =>
    operation.run(async () => {
      const id = selected;
      if (!ready || id === null) return;
      await adminApi.patch(`/support/tickets/${id}`, body);
      if (selectedRef.current === id) await detail.reload();
      await tickets.reload();
    });
  const send = (internal: boolean) =>
    operation.run(async () => {
      const id = selected;
      const content = internal ? note : text;
      if (!ready || id === null || !content.trim()) return;
      await adminApi.post(
        `/support/tickets/${id}/${internal ? "internal-notes" : "reply"}`,
        { content },
      );
      if (selectedRef.current === id) {
        if (internal) setNote("");
        else setText("");
        await detail.reload();
      }
      await tickets.reload();
    });
  const filter =
    (set: (value: string) => void) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      set(event.target.value);
      setOffset(0);
    };
  return (
    <div className="page-stack">
      <Filters>
        <label>
          Search
          <input value={search} onChange={filter(setSearch)} />
        </label>
        <label>
          Status
          <select value={status} onChange={filter(setStatus)}>
            <option value="">All</option>
            {[
              "open",
              "in_progress",
              "waiting_for_user",
              "resolved",
              "closed",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Priority
          <select value={priority} onChange={filter(setPriority)}>
            <option value="">All</option>
            {["low", "normal", "high", "urgent"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Assigned to
          <select value={assignee} onChange={filter(setAssignee)}>
            <option value="">All</option>
            {assignees.data.items.map((item: JsonRecord) => (
              <option value={item.id} key={item.id}>
                {item.full_name}
              </option>
            ))}
          </select>
        </label>
      </Filters>
      <PageState loading={tickets.loading} error={tickets.error} />
      <Panel title="Support queue">
        <DataTable
          rows={tickets.data.items}
          columns={[
            ...columns(
              "id",
              "subject",
              "status",
              "priority",
              "assigned_admin_id",
              "updated_at",
            ),
            {
              key: "user",
              label: "User",
              render: (ticket) => ticket.user?.username,
            },
            {
              key: "open",
              label: "Open",
              render: (ticket) => (
                <button
                  className="button ghost small"
                  disabled={operation.busy}
                  onClick={() => select(ticket.id)}
                >
                  Open ticket
                </button>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={tickets.data.total}
          onChange={setOffset}
          busy={tickets.loading}
        />
      </Panel>
      <ActionError error={operation.error} />
      {selected !== null && (
        <>
          <PageState loading={detail.loading} error={detail.error} />
          {ready && (
            <>
              <Panel title={`#${selected} · ${detail.data.ticket.subject}`}>
                <RecordDetails
                  value={{
                    status: detail.data.ticket.status,
                    priority: detail.data.ticket.priority,
                    user: detail.data.ticket.user,
                    assigned_admin_id: detail.data.ticket.assigned_admin_id,
                  }}
                />
                {can(props, "support.manage") && (
                  <Filters>
                    <label>
                      Status
                      <select
                        value={detail.data.ticket.status}
                        disabled={operation.busy}
                        onChange={(event) =>
                          void change({ status: event.target.value })
                        }
                      >
                        {[
                          "open",
                          "in_progress",
                          "waiting_for_user",
                          "resolved",
                          "closed",
                        ].map((item) => (
                          <option key={item}>{item}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Priority
                      <select
                        value={detail.data.ticket.priority}
                        disabled={operation.busy}
                        onChange={(event) =>
                          void change({ priority: event.target.value })
                        }
                      >
                        {["low", "normal", "high", "urgent"].map((item) => (
                          <option key={item}>{item}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Assignee
                      <select
                        value={detail.data.ticket.assigned_admin_id || ""}
                        disabled={operation.busy}
                        onChange={(event) =>
                          void change({
                            assigned_admin_id: event.target.value
                              ? Number(event.target.value)
                              : null,
                          })
                        }
                      >
                        <option value="">Unassigned</option>
                        {assignees.data.items.map((item: JsonRecord) => (
                          <option value={item.id} key={item.id}>
                            {item.full_name}
                          </option>
                        ))}
                      </select>
                    </label>
                  </Filters>
                )}
              </Panel>
              <Panel title="Conversation">
                <DataTable
                  rows={detail.data.messages || []}
                  columns={columns("from", "content", "created_at")}
                />
                {can(props, "support.reply") && (
                  <form
                    className="page-stack"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void send(false);
                    }}
                  >
                    <label>
                      Reply
                      <textarea
                        value={text}
                        maxLength={8000}
                        onChange={(event) => setText(event.target.value)}
                        required
                        disabled={
                          operation.busy ||
                          detail.data.ticket.status === "closed"
                        }
                      />
                    </label>
                    <button
                      className="button primary"
                      disabled={
                        operation.busy ||
                        !text.trim() ||
                        detail.data.ticket.status === "closed"
                      }
                    >
                      Send reply
                    </button>
                  </form>
                )}
              </Panel>
              <Panel title="Internal notes">
                <DataTable
                  rows={detail.data.internal_notes || []}
                  columns={columns("content", "admin", "created_at")}
                />
                {can(props, "support.manage") && (
                  <form
                    className="page-stack"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void send(true);
                    }}
                  >
                    <label>
                      Internal note
                      <textarea
                        value={note}
                        maxLength={8000}
                        onChange={(event) => setNote(event.target.value)}
                        required
                        disabled={operation.busy}
                      />
                    </label>
                    <button
                      className="button secondary"
                      disabled={operation.busy || !note.trim()}
                    >
                      Add note
                    </button>
                  </form>
                )}
              </Panel>
            </>
          )}
        </>
      )}
    </div>
  );
}

type NumberField = {
  key: string;
  label: string;
  min: number;
  max: number;
  step?: number;
};
const providerNumbers: NumberField[] = [
  { key: "priority", label: "Priority", min: 1, max: 1000 },
  { key: "trust_score", label: "Trust score", min: 0, max: 1, step: 0.01 },
  {
    key: "minimum_interval_seconds",
    label: "Minimum interval (seconds)",
    min: 1,
    max: 86400,
  },
  {
    key: "operational_ttl_seconds",
    label: "Operational TTL (seconds)",
    min: 5,
    max: 172800,
  },
  {
    key: "requests_per_minute",
    label: "Requests per minute",
    min: 0,
    max: 10000,
  },
  { key: "requests_per_hour", label: "Requests per hour", min: 0, max: 100000 },
  { key: "requests_per_day", label: "Requests per day", min: 0, max: 1000000 },
  {
    key: "reserved_anomaly_requests",
    label: "Anomaly request reserve",
    min: 0,
    max: 100000,
  },
  {
    key: "reserved_fallback_requests",
    label: "Fallback request reserve",
    min: 0,
    max: 100000,
  },
];
const sourceNumbers: NumberField[] = [
  { key: "trust_score", label: "Trust score", min: 0, max: 1, step: 0.01 },
  {
    key: "minimum_confidence",
    label: "Minimum confidence",
    min: 0,
    max: 1,
    step: 0.01,
  },
  {
    key: "maximum_message_age_seconds",
    label: "Maximum message age (seconds)",
    min: 30,
    max: 86400,
  },
  {
    key: "maximum_deviation_percent",
    label: "Maximum deviation (%)",
    min: 0.1,
    max: 50,
    step: 0.1,
  },
];
function NumberFields({
  fields,
  value,
  set,
}: {
  fields: NumberField[];
  value: JsonRecord;
  set: (value: JsonRecord) => void;
}) {
  return (
    <>
      {fields.map((field) => (
        <label key={field.key}>
          {field.label}
          <input
            type="number"
            min={field.min}
            max={field.max}
            step={field.step || 1}
            value={value[field.key] ?? ""}
            onChange={(event) =>
              set({
                ...value,
                [field.key]:
                  event.target.value === ""
                    ? undefined
                    : Number(event.target.value),
              })
            }
          />
        </label>
      ))}
    </>
  );
}
const defaultSource = () => ({
  channel_id: "",
  username: "",
  display_name: "",
  source_type: "channel",
  allowed_instruments: ["USDT_TOMAN"],
  role: "verifier",
  trust_score: 0.5,
  minimum_confidence: 0.8,
  maximum_message_age_seconds: 300,
  maximum_deviation_percent: 3,
  requires_multiple_sources: false,
  parser_type: "strict_explicit",
  parser_version: "strict-explicit-3",
  enabled: true,
});

export function ProvidersPage(props: PageProps) {
  const providers = useResource<JsonRecord>(
    `/providers?refresh=${props.refreshKey}`,
    { items: [] },
  );
  const [draftStatus, setDraftStatus] = useState("draft");
  const [draftOffset, setDraftOffset] = useState(0);
  const drafts = useResource<JsonRecord>(
    `/providers/drafts?${query({ status: draftStatus, limit: PAGE_SIZE, offset: draftOffset, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const [selectedProvider, setSelectedProvider] = useState<JsonRecord | null>(
    null,
  );
  const [providerValue, setProviderValue] = useState<JsonRecord>({});
  const operation = useOperation();
  const createDraft = (event: React.FormEvent) => {
    event.preventDefault();
    void operation.run(async () => {
      if (!selectedProvider) return;
      const body = Object.fromEntries(
        ["enabled", "role", ...providerNumbers.map((field) => field.key)]
          .filter(
            (key) =>
              providerValue[key] !== undefined && providerValue[key] !== null,
          )
          .map((key) => [key, providerValue[key]]),
      );
      await adminApi.post(
        `/providers/${selectedProvider.provider_id}/drafts`,
        body,
      );
      setSelectedProvider(null);
      await drafts.reload();
    });
  };
  return (
    <div className="page-stack">
      <PageState loading={providers.loading} error={providers.error} />
      <ActionError error={operation.error} />
      <Panel title="Provider catalogue">
        <DataTable
          rows={providers.data.items}
          rowKey="provider_id"
          columns={[
            ...columns(
              "provider_id",
              "asset",
              "enabled",
              "role",
              "priority",
              "trust_score",
              "operational_ttl_seconds",
              "credential_status",
            ),
            {
              key: "edit",
              label: "Configuration",
              render: (provider) =>
                can(props, "providers.manage") && (
                  <button
                    className="button ghost small"
                    disabled={operation.busy}
                    onClick={() => {
                      setSelectedProvider(provider);
                      setProviderValue(
                        Object.fromEntries(
                          [
                            "enabled",
                            "role",
                            ...providerNumbers.map((field) => field.key),
                          ].map((key) => [
                            key,
                            provider[key] === null
                              ? undefined
                              : ["enabled", "role"].includes(key) ||
                                  provider[key] === undefined
                                ? provider[key]
                                : Number(provider[key]),
                          ]),
                        ),
                      );
                    }}
                  >
                    Create draft
                  </button>
                ),
            },
          ]}
        />
      </Panel>
      {selectedProvider && (
        <Panel title={`Configure ${selectedProvider.provider_id}`}>
          <form onSubmit={createDraft} className="page-stack">
            <Filters>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={providerValue.enabled ?? true}
                  onChange={(event) =>
                    setProviderValue({
                      ...providerValue,
                      enabled: event.target.checked,
                    })
                  }
                />
                Enabled
              </label>
              <label>
                Role
                <select
                  value={providerValue.role || "fallback"}
                  onChange={(event) =>
                    setProviderValue({
                      ...providerValue,
                      role: event.target.value,
                    })
                  }
                >
                  {["primary", "verifier", "fallback", "compare"].map(
                    (item) => (
                      <option key={item}>{item}</option>
                    ),
                  )}
                </select>
              </label>
              <NumberFields
                fields={providerNumbers}
                value={providerValue}
                set={setProviderValue}
              />
            </Filters>
            <div className="row-actions">
              <button className="button primary" disabled={operation.busy}>
                Create review draft
              </button>
              <button
                type="button"
                className="button ghost"
                onClick={() => setSelectedProvider(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        </Panel>
      )}
      <Panel title="Provider change history">
        <Filters>
          <label>
            Status
            <select
              value={draftStatus}
              onChange={(event) => {
                setDraftStatus(event.target.value);
                setDraftOffset(0);
              }}
            >
              <option value="">All</option>
              {["draft", "applied", "rejected"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
        </Filters>
        <PageState loading={drafts.loading} error={drafts.error} />
        <DataTable
          rows={drafts.data.items}
          columns={[
            ...columns(
              "id",
              "provider_id",
              "status",
              "created_at",
              "created_by",
              "applied_by",
            ),
            {
              key: "diff",
              label: "Change and impact",
              render: (draft) => (
                <details>
                  <summary>Compare</summary>
                  <RecordDetails
                    value={{
                      before: draft.before,
                      proposed: draft.proposed,
                      impact: draft.impact,
                    }}
                  />
                </details>
              ),
            },
            {
              key: "actions",
              label: "Actions",
              render: (draft) =>
                can(props, "providers.manage") && draft.status === "applied" ? (
                  <button
                    className="button ghost small"
                    disabled={operation.busy}
                    onClick={() =>
                      void operation.run(async () => {
                        await adminApi.post(
                          `/providers/drafts/${draft.id}/rollback`,
                        );
                        await drafts.reload();
                      })
                    }
                  >
                    Create rollback draft
                  </button>
                ) : (
                  can(props, "providers.manage") &&
                  draft.status === "draft" && (
                    <div className="row-actions">
                      <button
                        className="button secondary small"
                        onClick={() =>
                          props.onDanger({
                            title: `Apply provider draft ${draft.id}`,
                            expected: `APPLY PROVIDER ${draft.provider_id}`,
                            impact: formatValue(draft.impact),
                            execute: async (confirmation) => {
                              await adminApi.post(
                                `/providers/drafts/${draft.id}/apply`,
                                { confirmation },
                              );
                            },
                          })
                        }
                      >
                        Apply
                      </button>
                      <button
                        className="button danger small"
                        disabled={operation.busy}
                        onClick={() =>
                          void operation.run(async () => {
                            await adminApi.post(
                              `/providers/drafts/${draft.id}/reject`,
                            );
                            await drafts.reload();
                          })
                        }
                      >
                        Reject
                      </button>
                    </div>
                  )
                ),
            },
          ]}
        />
        <Pagination
          offset={draftOffset}
          limit={PAGE_SIZE}
          total={drafts.data.total}
          onChange={setDraftOffset}
          busy={drafts.loading}
        />
      </Panel>
      {can(props, "telegram.read") && <TelegramSources {...props} />}
    </div>
  );
}

export function TelegramPage(props: PageProps) {
  return (
    <div className="page-stack">
      <TelegramSources {...props} />
    </div>
  );
}

function TelegramSources(props: PageProps) {
  const [offset, setOffset] = useState(0);
  const sources = useResource<JsonRecord>(
    `/telegram/sources?${query({ offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], recent_rejections: [], instrument_ids: [], total: 0 },
  );
  const [editing, setEditing] = useState<JsonRecord | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [value, setValue] = useState<JsonRecord>(defaultSource());
  const [previewId, setPreviewId] = useState("");
  const [previewText, setPreviewText] = useState("");
  const [preview, setPreview] = useState<JsonRecord[]>([]);
  const operation = useOperation();
  const edit = (source: JsonRecord | null) => {
    setEditing(source);
    setValue(
      source
        ? {
            ...source,
            ...Object.fromEntries(
              sourceNumbers.map((field) => [
                field.key,
                Number(source[field.key]),
              ]),
            ),
          }
        : defaultSource(),
    );
    setShowForm(true);
  };
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const fields = [
      "enabled",
      "role",
      "requires_multiple_sources",
      "allowed_instruments",
      "parser_type",
      "parser_version",
      ...sourceNumbers.map((field) => field.key),
    ];
    const body = Object.fromEntries(fields.map((key) => [key, value[key]]));
    const expected = editing
      ? `UPDATE TELEGRAM SOURCE ${editing.source_id}`
      : `CREATE TELEGRAM SOURCE ${value.channel_id}`;
    props.onDanger({
      title: expected,
      expected,
      impact:
        "Source policy changes affect quote acceptance. Use preview before enabling a source.",
      execute: async (confirmation) => {
        if (editing)
          await adminApi.patch(`/telegram/sources/${editing.source_id}`, {
            ...body,
            confirmation,
          });
        else
          await adminApi.post("/telegram/sources", {
            ...body,
            channel_id: value.channel_id,
            username: value.username || null,
            display_name: value.display_name,
            source_type: value.source_type,
            confirmation,
          });
      },
    });
  };
  return (
    <>
      <Panel title="Telegram sources">
        <PageState loading={sources.loading} error={sources.error} />
        {can(props, "telegram.manage") && (
          <button className="button primary" onClick={() => edit(null)}>
            New source
          </button>
        )}
        <DataTable
          rows={sources.data.items}
          rowKey="source_id"
          columns={[
            ...columns(
              "source_id",
              "channel_id",
              "display_name",
              "enabled",
              "role",
              "trust_score",
              "parser_type",
              "allowed_instruments",
            ),
            {
              key: "actions",
              label: "Actions",
              render: (source) => (
                <div className="row-actions">
                  {can(props, "telegram.manage") && (
                    <button
                      className="button ghost small"
                      onClick={() => edit(source)}
                    >
                      Edit policy
                    </button>
                  )}
                  <button
                    className="button ghost small"
                    onClick={() => {
                      setPreviewId(source.source_id);
                      setPreview([]);
                    }}
                  >
                    Preview parser
                  </button>
                </div>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={sources.data.total}
          onChange={setOffset}
          busy={sources.loading}
        />
      </Panel>
      {showForm && (
        <Panel
          title={
            editing ? `Edit source ${editing.source_id}` : "New Telegram source"
          }
        >
          <form onSubmit={submit} className="page-stack">
            <Filters>
              {!editing && (
                <>
                  <label>
                    Marked chat ID
                    <input
                      value={value.channel_id}
                      required
                      pattern="-100[0-9]+"
                      placeholder="-1001234567890"
                      onChange={(event) =>
                        setValue({ ...value, channel_id: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Username
                    <input
                      value={value.username}
                      onChange={(event) =>
                        setValue({ ...value, username: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Display name
                    <input
                      value={value.display_name}
                      minLength={2}
                      maxLength={160}
                      required
                      onChange={(event) =>
                        setValue({ ...value, display_name: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Source type
                    <select
                      value={value.source_type}
                      onChange={(event) =>
                        setValue({ ...value, source_type: event.target.value })
                      }
                    >
                      <option>channel</option>
                      <option>group</option>
                    </select>
                  </label>
                </>
              )}
              <label>
                Role
                <select
                  value={value.role}
                  onChange={(event) =>
                    setValue({ ...value, role: event.target.value })
                  }
                >
                  {["compare", "verifier", "fallback"].map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </label>
              <label>
                Parser
                <select
                  value={value.parser_type}
                  onChange={(event) =>
                    setValue({ ...value, parser_type: event.target.value })
                  }
                >
                  <option>strict_explicit</option>
                  <option>strict_hashtag</option>
                </select>
              </label>
              <label>
                Parser version
                <input
                  value={value.parser_version}
                  required
                  onChange={(event) =>
                    setValue({ ...value, parser_version: event.target.value })
                  }
                />
              </label>
              <NumberFields
                fields={sourceNumbers}
                value={value}
                set={setValue}
              />
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={value.enabled}
                  onChange={(event) =>
                    setValue({ ...value, enabled: event.target.checked })
                  }
                />
                Enabled
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={value.requires_multiple_sources}
                  onChange={(event) =>
                    setValue({
                      ...value,
                      requires_multiple_sources: event.target.checked,
                    })
                  }
                />
                Require independent sources
              </label>
            </Filters>
            <div className="check-grid">
              {sources.data.instrument_ids.map((id: string) => {
                return (
                  <label className="check-label" key={id}>
                    <input
                      type="checkbox"
                      checked={value.allowed_instruments?.includes(id)}
                      onChange={() =>
                        setValue({
                          ...value,
                          allowed_instruments:
                            value.allowed_instruments.includes(id)
                              ? value.allowed_instruments.filter(
                                  (entry: string) => entry !== id,
                                )
                              : [...value.allowed_instruments, id],
                        })
                      }
                    />
                    {id}
                  </label>
                );
              })}
            </div>
            <div className="row-actions">
              <button
                className="button primary"
                disabled={!value.allowed_instruments?.length}
              >
                Review source policy
              </button>
              <button
                type="button"
                className="button ghost"
                onClick={() => setShowForm(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </Panel>
      )}
      {previewId && (
        <Panel title={`Parser preview · source ${previewId}`}>
          <form
            className="page-stack"
            onSubmit={(event) => {
              event.preventDefault();
              void operation.run(async () => {
                const result = await adminApi.post<JsonRecord>(
                  `/telegram/sources/${previewId}/preview`,
                  { text: previewText },
                );
                setPreview(result.items);
              });
            }}
          >
            <label>
              Sample message
              <textarea
                maxLength={8000}
                required
                value={previewText}
                onChange={(event) => setPreviewText(event.target.value)}
              />
            </label>
            <button className="button secondary" disabled={operation.busy}>
              Parse sample
            </button>
            <ActionError error={operation.error} />
          </form>
          <DataTable
            rows={preview}
            columns={columns(
              "instrument_id",
              "price",
              "currency",
              "weight_unit",
              "purity",
              "confidence_score",
              "validation_status",
              "rejection_reason",
              "parser_version",
            )}
          />
        </Panel>
      )}
      <Panel title="Recent rejected messages">
        <DataTable
          rows={sources.data.recent_rejections}
          columns={columns(
            "id",
            "telegram_message_id",
            "instrument_id",
            "validation_status",
            "rejection_reason",
            "created_at",
          )}
        />
      </Panel>
    </>
  );
}

export function PricingPage(props: PageProps) {
  const instruments = useResource<JsonRecord>(
    `/pricing/instruments?refresh=${props.refreshKey}`,
    { items: [] },
  );
  const [selected, setSelected] = useState("");
  const detail = useResource<JsonRecord>(
    selected
      ? `/pricing/instruments/${selected}?history_limit=200`
      : "/pricing/instruments",
    {},
  );
  const [status, setStatus] = useState("open");
  const [offset, setOffset] = useState(0);
  const anomalies = useResource<JsonRecord>(
    `/pricing/anomalies?${query({ status, offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [refreshReason, setRefreshReason] = useState("");
  const operation = useOperation();
  const review = (anomaly: JsonRecord, result: string) =>
    operation.run(async () => {
      await adminApi.post(`/pricing/anomalies/${anomaly.id}/review`, {
        status: result,
        note: notes[String(anomaly.id)],
      });
      await anomalies.reload();
      if (selected) await detail.reload();
    });
  return (
    <div className="page-stack">
      <PageState loading={instruments.loading} error={instruments.error} />
      <ActionError error={operation.error} />
      <Panel title="Instruments">
        <DataTable
          rows={instruments.data.items}
          rowKey="instrument_id"
          columns={[
            ...columns(
              "instrument_id",
              "quote_currency",
              "weight_unit",
              "purity",
              "enabled",
            ),
            {
              key: "latest",
              label: "Latest canonical",
              render: (item) => (
                <details>
                  <summary>
                    {formatValue(item.latest_canonical?.price)} ·{" "}
                    {formatValue(item.latest_canonical?.status)}
                  </summary>
                  <RecordDetails value={item.latest_canonical} />
                </details>
              ),
            },
            {
              key: "open",
              label: "Details",
              render: (item) => (
                <button
                  className="button ghost small"
                  onClick={() => setSelected(item.instrument_id)}
                >
                  History and sources
                </button>
              ),
            },
          ]}
        />
      </Panel>
      {selected && (
        <>
          <PageState loading={detail.loading} error={detail.error} />
          {!detail.loading &&
            detail.data.instrument?.instrument_id === selected && (
              <>
                <Panel title={selected}>
                  <RecordDetails value={detail.data.instrument} />
                  <RecordDetails value={detail.data.latest_canonical} />
                  {can(props, "pricing.manage") && (
                    <form
                      className="inline-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void operation.run(async () => {
                          await adminApi.post(
                            `/pricing/instruments/${selected}/refresh`,
                            { reason: refreshReason },
                          );
                          setRefreshReason("");
                        });
                      }}
                    >
                      <label>
                        Refresh reason
                        <input
                          minLength={3}
                          maxLength={240}
                          required
                          value={refreshReason}
                          onChange={(event) =>
                            setRefreshReason(event.target.value)
                          }
                        />
                      </label>
                      <button
                        className="button secondary"
                        disabled={operation.busy}
                      >
                        Queue budget-controlled refresh
                      </button>
                    </form>
                  )}
                </Panel>
                <DetailTables
                  value={detail.data}
                  fields={{
                    canonical_history: [
                      "price",
                      "status",
                      "observed_at",
                      "canonical_at",
                      "valid_until",
                      "is_persisted",
                      "decision_reason",
                      "source_summary",
                    ],
                    source_quotes: [
                      "provider_id",
                      "price",
                      "currency",
                      "weight_unit",
                      "purity",
                      "observed_at",
                      "validation_status",
                      "confidence_score",
                      "is_derived",
                      "rejection_reason",
                    ],
                    verifications: [
                      "id",
                      "anomaly_id",
                      "candidate_quote_id",
                      "verifier_quote_ids",
                      "decision",
                      "tolerance_percent",
                      "decision_reason",
                      "created_at",
                    ],
                  }}
                />
              </>
            )}
        </>
      )}
      <Panel title="Anomaly review">
        <label>
          Status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            {["open", "reviewed", "dismissed", "resolved"].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <PageState loading={anomalies.loading} error={anomalies.error} />
        <DataTable
          rows={anomalies.data.items}
          columns={[
            ...columns(
              "id",
              "instrument_id",
              "candidate_price",
              "previous_price",
              "deviation_percent",
              "dynamic_threshold_percent",
              "severity",
              "status",
            ),
            {
              key: "proof",
              label: "Quote proof",
              render: (anomaly) => (
                <details>
                  <summary>Time, unit and source</summary>
                  <RecordDetails
                    value={{
                      candidate: anomaly.candidate_quote,
                      previous: anomaly.previous_canonical,
                      reason: anomaly.reason,
                      admin_review: anomaly.admin_review,
                    }}
                  />
                </details>
              ),
            },
            {
              key: "review",
              label: "Review",
              render: (anomaly) =>
                can(props, "pricing.manage") &&
                ["open", "reviewed"].includes(anomaly.status) && (
                  <div className="review-controls">
                    <label>
                      Review note
                      <input
                        maxLength={1000}
                        minLength={3}
                        value={notes[String(anomaly.id)] || ""}
                        onChange={(event) =>
                          setNotes({
                            ...notes,
                            [String(anomaly.id)]: event.target.value,
                          })
                        }
                      />
                    </label>
                    <div className="row-actions">
                      {(anomaly.status === "open"
                        ? ["reviewed", "dismissed", "resolved"]
                        : ["dismissed", "resolved"]
                      ).map((result) => (
                        <button
                          key={result}
                          className="button ghost small"
                          disabled={
                            operation.busy ||
                            (notes[String(anomaly.id)] || "").trim().length < 3
                          }
                          onClick={() => void review(anomaly, result)}
                        >
                          {result}
                        </button>
                      ))}
                    </div>
                  </div>
                ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={anomalies.data.total}
          onChange={setOffset}
          busy={anomalies.loading}
        />
      </Panel>
    </div>
  );
}

export function JobsPage(props: PageProps) {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [dlqOffset, setDlqOffset] = useState(0);
  const jobs = useResource<JsonRecord>(
    `/jobs?${query({ status, offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { admin_jobs: [], backfill_jobs: [], delivery_jobs: [], totals: {} },
  );
  const dlq = useResource<JsonRecord>(
    `/jobs/dlq?${query({ offset: dlqOffset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
    can(props, "dlq.read"),
  );
  const operation = useOperation();
  const retry = (kind: string, id: string | number) =>
    operation.run(async () => {
      await adminApi.post(
        `/jobs/${kind === "admin" ? "" : kind + "/"}${id}/retry`,
      );
      await jobs.reload();
      if (can(props, "dlq.read")) await dlq.reload();
    });
  const cancel = (kind: string, job: JsonRecord) => {
    const expected =
      kind === "admin"
        ? `CANCEL ADMIN JOB ${job.id}`
        : kind === "backfill"
          ? `CANCEL BACKFILL ${job.id}`
          : `CANCEL DELIVERY ${job.id}`;
    props.onDanger({
      title: expected,
      expected,
      impact:
        kind === "delivery"
          ? "Queued or claimed work cancels atomically. A delivery already sending cannot be recalled."
          : "Only queued jobs cancel. Processing jobs return a conflict.",
      execute: async (confirmation) => {
        await adminApi.post(
          `/jobs/${kind === "admin" ? "" : kind + "/"}${job.id}/cancel`,
          { confirmation },
        );
      },
    });
  };
  const actions = (kind: string) => ({
    key: "actions",
    label: "Actions",
    render: (job: JsonRecord) => (
      <div className="row-actions">
        {can(props, kind === "delivery" ? "dlq.manage" : "jobs.manage") && (
          <>
            {(kind === "delivery"
              ? ["dead", "failed", "retrying"]
              : [
                  "dead",
                  "failed",
                  "cancelled",
                  ...(kind === "backfill" ? ["deferred"] : []),
                ]
            ).includes(job.status) && (
              <button
                className="button secondary small"
                disabled={operation.busy}
                onClick={() => void retry(kind, job.id)}
              >
                Retry
              </button>
            )}
            {(kind === "delivery"
              ? ["pending", "retrying", "processing", "failed", "dead"]
              : ["pending", "retrying", "deferred", "failed", "dead"]
            ).includes(job.status) && (
              <button
                className="button danger small"
                disabled={operation.busy}
                onClick={() => cancel(kind, job)}
              >
                Cancel
              </button>
            )}
          </>
        )}
        <details>
          <summary>Details</summary>
          <RecordDetails value={job} />
        </details>
      </div>
    ),
  });
  const total = Math.max(
    0,
    ...Object.values(jobs.data.totals || {}).map(Number),
  );
  return (
    <div className="page-stack">
      <Filters>
        <label>
          Status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            {[
              "pending",
              "processing",
              "sending",
              "retrying",
              "deferred",
              "completed",
              "delivered",
              "failed",
              "dead",
              "cancelled",
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <button
          className="button ghost"
          disabled={jobs.loading}
          onClick={() => void jobs.reload()}
        >
          Refresh jobs
        </button>
      </Filters>
      <PageState loading={jobs.loading} error={jobs.error} />
      <ActionError error={operation.error} />
      <Panel title="Administrator jobs">
        <DataTable
          rows={jobs.data.admin_jobs}
          columns={[
            ...columns(
              "id",
              "job_type",
              "resource_id",
              "status",
              "attempt_count",
              "next_attempt_at",
              "last_error",
              "completed_at",
            ),
            actions("admin"),
          ]}
        />
      </Panel>
      <Panel title="History backfill">
        <DataTable
          rows={jobs.data.backfill_jobs}
          columns={[
            ...columns(
              "id",
              "instrument_id",
              "range_start",
              "range_end",
              "status",
              "attempt_count",
              "next_attempt_at",
              "last_error",
            ),
            actions("backfill"),
          ]}
        />
      </Panel>
      <Panel title="Deliveries">
        <DataTable
          rows={jobs.data.delivery_jobs}
          columns={[
            ...columns(
              "id",
              "alert_id",
              "channel",
              "status",
              "attempt_count",
              "next_retry_at",
              "last_error",
              "delivered_at",
            ),
            actions("delivery"),
          ]}
        />
      </Panel>
      <Pagination
        offset={offset}
        limit={PAGE_SIZE}
        total={total}
        onChange={setOffset}
        busy={jobs.loading}
      />
      {can(props, "dlq.read") && (
        <Panel title="Dead-letter queue">
          <PageState loading={dlq.loading} error={dlq.error} />
          <DataTable
            rows={dlq.data.items}
            columns={[
              ...columns(
                "id",
                "alert_id",
                "channel",
                "attempt_count",
                "last_error",
                "dead_at",
              ),
              actions("delivery"),
            ]}
          />
          <Pagination
            offset={dlqOffset}
            limit={PAGE_SIZE}
            total={dlq.data.total}
            onChange={setDlqOffset}
            busy={dlq.loading}
          />
        </Panel>
      )}
    </div>
  );
}

export function DlqPage(props: PageProps) {
  const [offset, setOffset] = useState(0);
  const resource = useResource<JsonRecord>(
    `/jobs/dlq?${query({ offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const operation = useOperation();
  return (
    <div className="page-stack">
      <PageState loading={resource.loading} error={resource.error} />
      <ActionError error={operation.error} />
      <Panel title="Dead-letter queue">
        <DataTable
          rows={resource.data.items}
          columns={[
            ...columns(
              "id",
              "alert_id",
              "channel",
              "status",
              "attempt_count",
              "last_error",
              "dead_at",
            ),
            {
              key: "actions",
              label: "Actions",
              render: (job) => (
                <div className="row-actions">
                  {can(props, "dlq.manage") && (
                    <>
                      <button
                        className="button secondary small"
                        disabled={operation.busy}
                        onClick={() =>
                          void operation.run(async () => {
                            await adminApi.post(
                              `/jobs/delivery/${job.id}/retry`,
                            );
                            await resource.reload();
                          })
                        }
                      >
                        Retry
                      </button>
                      <button
                        className="button danger small"
                        disabled={operation.busy}
                        onClick={() =>
                          props.onDanger({
                            title: "Cancel delivery",
                            expected: `CANCEL DELIVERY ${job.id}`,
                            impact:
                              "The failed delivery is cancelled. No message is sent.",
                            execute: async (confirmation) => {
                              await adminApi.post(
                                `/jobs/delivery/${job.id}/cancel`,
                                { confirmation },
                              );
                            },
                          })
                        }
                      >
                        Cancel
                      </button>
                    </>
                  )}
                  <details>
                    <summary>Details</summary>
                    <RecordDetails value={job} />
                  </details>
                </div>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={resource.data.total}
          onChange={setOffset}
          busy={resource.loading}
        />
      </Panel>
    </div>
  );
}

export function SettingsPage(props: PageProps) {
  const resource = useResource<JsonRecord>(
    `/settings?refresh=${props.refreshKey}`,
    {
      operational_settings: [],
      feature_flags: [],
      allowed_keys: [],
      instrument_scopes: [],
      provider_scopes: [],
      telegram_scopes: [],
    },
  );
  const [key, setKey] = useState("comparison_visible");
  const [scope, setScope] = useState("global");
  const [value, setValue] = useState<string | boolean>("");
  const effective = useResource<JsonRecord>(
    `/settings/effective?${query({ scope_id: scope, refresh: props.refreshKey })}`,
    { items: [] },
  );
  const operation = useOperation();
  const booleanKey = [
    "comparison_visible",
    "derived_fallback_enabled",
    "backfill_enabled",
    "telegram_source_enabled",
  ].includes(key);
  const stored = resource.data.operational_settings.find(
    (item: JsonRecord) => item.key === key && item.scope_id === scope,
  );
  const current = effective.data.items.find(
    (item: JsonRecord) => item.key === key,
  );
  useEffect(() => {
    const resolved = stored?.value ?? current?.effective_value;
    setValue(
      booleanKey
        ? resolved === true
        : resolved === null || resolved === undefined
          ? ""
          : String(resolved),
    );
  }, [key, scope, stored?.value, current?.effective_value, booleanKey]);
  const body = () => ({
    key,
    scope_id: scope,
    value: booleanKey ? value === true : Number(value),
    expected_version: stored?.version || 0,
  });
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    const dangerous =
      [
        "anomaly_threshold_percent",
        "canonical_expiry_seconds",
        "provider_budget_requests_per_hour",
      ].includes(key) ||
      (key === "derived_fallback_enabled" && value === true);
    if (dangerous)
      props.onDanger({
        title: "Change operational policy",
        expected: `CHANGE SETTING ${key}:${scope}`,
        impact:
          "Runtime policy changes on the next read. Concurrent edits fail with a version conflict.",
        execute: async (confirmation) => {
          await adminApi.put("/settings/operational", {
            ...body(),
            confirmation,
          });
        },
      });
    else
      void operation.run(async () => {
        await adminApi.put("/settings/operational", body());
        await resource.reload();
        await effective.reload();
      });
  };
  const scopes =
    key === "provider_budget_requests_per_hour"
      ? resource.data.provider_scopes
      : key === "telegram_source_enabled"
        ? resource.data.telegram_scopes
        : resource.data.instrument_scopes;
  return (
    <div className="page-stack">
      <PageState loading={resource.loading} error={resource.error} />
      <ActionError error={operation.error} />
      <Panel title="Deployment controls">
        <RecordDetails value={resource.data.environment} />
      </Panel>
      <Panel title="Feature defaults">
        <DataTable
          rows={resource.data.feature_flags}
          rowKey="key"
          columns={[
            ...columns(
              "key",
              "enabled",
              "description",
              "environment_authoritative",
            ),
            {
              key: "action",
              label: "Change",
              render: (flag) =>
                !flag.environment_authoritative &&
                can(props, "settings.manage") && (
                  <button
                    className="button ghost small"
                    disabled={operation.busy}
                    onClick={() => {
                      if (
                        flag.key === "derived_fallback_enabled" &&
                        !flag.enabled
                      )
                        props.onDanger({
                          title: "Enable derived fallback",
                          expected: "ENABLE DERIVED FALLBACK",
                          impact:
                            "Only instruments with a permitted derived policy can use this fallback.",
                          execute: async (confirmation) => {
                            await adminApi.patch(
                              `/settings/feature-flags/${flag.key}`,
                              { enabled: true, confirmation },
                            );
                          },
                        });
                      else
                        void operation.run(async () => {
                          await adminApi.patch(
                            `/settings/feature-flags/${flag.key}`,
                            { enabled: !flag.enabled },
                          );
                          await resource.reload();
                          await effective.reload();
                        });
                    }}
                  >
                    {flag.enabled ? "Disable" : "Enable"}
                  </button>
                ),
            },
          ]}
        />
      </Panel>
      <Panel title="Effective operational policy">
        <Filters>
          <label>
            Setting
            <select
              value={key}
              onChange={(event) => {
                setKey(event.target.value);
                setScope("global");
              }}
            >
              {resource.data.allowed_keys.map((item: JsonRecord) => (
                <option value={item.key} key={item.key}>
                  {item.key.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Scope
            <select
              value={scope}
              onChange={(event) => setScope(event.target.value)}
            >
              <option value="global">Global</option>
              {scopes.map((item: string) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
        </Filters>
        <PageState loading={effective.loading} error={effective.error} />
        <DataTable
          rows={effective.data.items}
          rowKey="key"
          columns={columns(
            "key",
            "scope_id",
            "effective_value",
            "source",
            "version",
          )}
        />
        {can(props, "settings.manage") && (
          <form onSubmit={save} className="page-stack">
            {booleanKey ? (
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={value === true}
                  onChange={(event) => setValue(event.target.checked)}
                />
                Enabled
              </label>
            ) : (
              <label>
                New value
                <input
                  type="number"
                  required
                  min={
                    key === "anomaly_threshold_percent"
                      ? 0.1
                      : key === "canonical_expiry_seconds"
                        ? 30
                        : 0
                  }
                  max={
                    key === "anomaly_threshold_percent"
                      ? 25
                      : key === "canonical_expiry_seconds"
                        ? 172800
                        : 100000
                  }
                  step={key === "anomaly_threshold_percent" ? 0.1 : 1}
                  value={String(value)}
                  onChange={(event) => setValue(event.target.value)}
                />
              </label>
            )}
            <p>
              Stored version: {stored?.version || 0}. Removing this override
              restores inherited policy.
            </p>
            <div className="row-actions">
              <button
                className="button primary"
                disabled={operation.busy || effective.loading}
              >
                Review or save
              </button>
              {stored && (
                <button
                  type="button"
                  className="button danger"
                  onClick={() =>
                    props.onDanger({
                      title: "Reset override",
                      expected: `RESET SETTING ${key}:${scope}`,
                      impact:
                        "The scoped override is removed. Inherited values become effective.",
                      execute: async (confirmation) => {
                        await adminApi.post("/settings/operational/reset", {
                          ...body(),
                          value: stored.value,
                          confirmation,
                        });
                      },
                    })
                  }
                >
                  Reset override
                </button>
              )}
            </div>
          </form>
        )}
      </Panel>
      <Panel title="Stored overrides">
        <DataTable
          rows={resource.data.operational_settings.map((item: JsonRecord) => ({
            ...item,
            identity: `${item.key}:${item.scope_id}`,
          }))}
          rowKey="identity"
          columns={columns(
            "key",
            "scope_id",
            "value",
            "version",
            "updated_by",
            "updated_at",
          )}
        />
      </Panel>
    </div>
  );
}

export function AuditPage(props: PageProps) {
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [result, setResult] = useState("");
  const [actor, setActor] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [offset, setOffset] = useState(0);
  const filters = {
    action,
    resource_type: resourceType,
    result,
    actor_admin_id: actor,
    since: since ? new Date(since).toISOString() : undefined,
    until: until ? new Date(until).toISOString() : undefined,
  };
  const resource = useResource<JsonRecord>(
    `/audit?${query({ ...filters, offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const operation = useOperation();
  const filter =
    (set: (value: string) => void) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      set(event.target.value);
      setOffset(0);
    };
  const exportRows = () =>
    operation.run(async () => {
      const blob = await adminApi.download(`/audit/export?${query(filters)}`);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = "audit.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    });
  return (
    <div className="page-stack">
      <Filters>
        <label>
          Exact action
          <input value={action} onChange={filter(setAction)} maxLength={120} />
        </label>
        <label>
          Resource type
          <input
            value={resourceType}
            onChange={filter(setResourceType)}
            maxLength={80}
          />
        </label>
        <label>
          Result
          <select value={result} onChange={filter(setResult)}>
            <option value="">All</option>
            <option>success</option>
            <option>denied</option>
            <option>failed</option>
          </select>
        </label>
        <label>
          Actor ID
          <input
            type="number"
            min={1}
            value={actor}
            onChange={filter(setActor)}
          />
        </label>
        <label>
          From
          <input
            type="datetime-local"
            value={since}
            onChange={filter(setSince)}
          />
        </label>
        <label>
          Until
          <input
            type="datetime-local"
            value={until}
            onChange={filter(setUntil)}
          />
        </label>
      </Filters>
      <button
        className="button secondary"
        disabled={operation.busy}
        onClick={() => void exportRows()}
      >
        Export filtered records (up to 500)
      </button>
      <ActionError error={operation.error} />
      <PageState loading={resource.loading} error={resource.error} />
      <Panel title="Audit trail">
        <DataTable
          rows={resource.data.items}
          columns={[
            ...columns(
              "id",
              "actor_admin_id",
              "action",
              "resource_type",
              "resource_id",
              "result",
              "created_at",
              "request_id",
            ),
            {
              key: "diff",
              label: "Before / after",
              render: (item) => (
                <details>
                  <summary>Show change</summary>
                  <RecordDetails
                    value={{
                      before: item.before,
                      after: item.after,
                      detail: item.detail,
                      ip_address: item.ip_address,
                    }}
                  />
                </details>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={resource.data.total}
          onChange={setOffset}
          busy={resource.loading}
        />
      </Panel>
    </div>
  );
}

export function AlertsPage(props: PageProps) {
  const [user, setUser] = useState("");
  const [active, setActive] = useState("");
  const [instrument, setInstrument] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const resource = useResource<JsonRecord>(
    `/alerts?${query({ user_id: user, active, instrument_id: instrument, offset, limit: PAGE_SIZE, refresh: props.refreshKey })}`,
    { items: [], total: 0 },
  );
  const detail = useResource<JsonRecord>(
    selected ? `/alerts/${selected}` : "/alerts?limit=1",
    {},
  );
  const change = (alert: JsonRecord) =>
    props.onDanger({
      title: "Change alert state",
      expected: `${alert.is_active ? "DISABLE" : "ENABLE"} ALERT ${alert.id}`,
      impact:
        "Only future alert evaluations change. Existing delivery jobs require separate cancellation.",
      execute: async (confirmation) => {
        await adminApi.patch(`/alerts/${alert.id}/state`, {
          is_active: !alert.is_active,
          reason,
          confirmation,
        });
      },
    });
  const filter =
    (set: (value: string) => void) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      set(event.target.value);
      setOffset(0);
    };
  return (
    <div className="page-stack">
      <Filters>
        <label>
          User ID
          <input
            type="number"
            min={1}
            value={user}
            onChange={filter(setUser)}
          />
        </label>
        <label>
          State
          <select value={active} onChange={filter(setActive)}>
            <option value="">All</option>
            <option value="true">Active</option>
            <option value="false">Disabled</option>
          </select>
        </label>
        <label>
          Instrument
          <input
            value={instrument}
            onChange={filter(setInstrument)}
            maxLength={64}
          />
        </label>
        {can(props, "alerts.manage") && (
          <label>
            Change reason
            <input
              value={reason}
              minLength={3}
              maxLength={240}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
        )}
      </Filters>
      <PageState loading={resource.loading} error={resource.error} />
      <Panel title="User alerts">
        <DataTable
          rows={resource.data.items}
          columns={[
            ...columns(
              "id",
              "user_id",
              "username",
              "instrument_id",
              "asset",
              "target_price",
              "condition",
              "currency_mode",
              "mode",
              "is_active",
              "triggered_at",
            ),
            {
              key: "actions",
              label: "Actions",
              render: (alert) => (
                <div className="row-actions">
                  <button
                    className="button ghost small"
                    onClick={() => setSelected(alert.id)}
                  >
                    Delivery history
                  </button>
                  {can(props, "alerts.manage") && (
                    <button
                      className="button secondary small"
                      disabled={reason.trim().length < 3}
                      onClick={() => change(alert)}
                    >
                      {alert.is_active ? "Disable" : "Enable"}
                    </button>
                  )}
                  <details>
                    <summary>Configuration</summary>
                    <RecordDetails value={alert} />
                  </details>
                </div>
              ),
            },
          ]}
        />
        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={resource.data.total}
          onChange={setOffset}
          busy={resource.loading}
        />
      </Panel>
      {selected !== null && (
        <>
          <PageState loading={detail.loading} error={detail.error} />
          {!detail.loading && detail.data.alert_id === selected && (
            <Panel title={`Alert ${selected} delivery history`}>
              <DataTable
                rows={detail.data.delivery_jobs}
                columns={columns(
                  "id",
                  "channel",
                  "status",
                  "attempt_count",
                  "last_error",
                  "provider_response_summary",
                  "created_at",
                  "delivered_at",
                )}
              />
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

export function BackupsPage(props: PageProps) {
  const resource = useResource<JsonRecord>(
    `/backups/status?refresh=${props.refreshKey}`,
    {},
  );
  return (
    <div className="page-stack">
      <PageState loading={resource.loading} error={resource.error} />
      <Panel
        title="Backup and restore evidence"
        action={
          <button
            className="button ghost"
            onClick={() => void resource.reload()}
          >
            Refresh
          </button>
        }
      >
        <RecordDetails value={resource.data} />
        <p className="muted">
          This status reports the configured manifest. A local drill does not
          prove recovery on the live host.
        </p>
      </Panel>
    </div>
  );
}
