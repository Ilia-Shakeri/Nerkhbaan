import type { CommunicationsClient, CommunicationsSnapshot, DeliveryEvent, CommunicationChannel, TestRecipient } from "./CommunicationsPage";

const initialSnapshot: CommunicationsSnapshot = {
  version: 1,
  encryption_ready: true,
  channels: {
    sms: { version: 1, enabled: true, provider_id: "kavenegar", ready: true, config: { sender: "1000001", template_id: "" }, credentials: { configured: true, masked: "••••••••" } },
    voip: { version: 0, enabled: false, provider_id: "asterisk_ari", ready: false, config: { endpoint: "https://pbx.example.test/ari", trunk: "alerts-trunk", ari_app: "nerkhbaan-alerts", caller_id: "", context: "", extension: "" }, credentials: { configured: false, masked: null } },
  },
  call_policy: { version: 0, enabled: false, critical_only: true, persist_seconds: 60, max_attempts: 1, cooldown_seconds: 900, max_calls_per_day: 10,
    quiet_hours: { enabled: true, start: "22:00", end: "08:00", timezone: "Asia/Tehran", critical_bypass: false } },
  provider_catalog: [
    { id: "kavenegar", label: "کاوه‌نگار", channels: ["sms"], config_fields: [
      { key: "sender", label: "شمارهٔ فرستنده", type: "text", required: true },
      { key: "template_id", label: "نام الگوی تأیید شماره", type: "text" },
    ], credential_fields: [{ key: "api_key", label: "کلید دسترسی سرویس", type: "secret", required: true }] },
    { id: "asterisk_ari", label: "مرکز تماس استریسک / ایزابل", channels: ["voip"], config_fields: [
      { key: "endpoint", label: "نشانی امن مرکز تلفن", type: "url", required: true },
      { key: "trunk", label: "نام ترانک PJSIP", type: "text", required: true },
      { key: "ari_app", label: "برنامهٔ آمادهٔ تماس", type: "text" },
      { key: "caller_id", label: "شمارهٔ تماس‌گیرنده", type: "text" },
      { key: "context", label: "زمینهٔ برنامهٔ تماس", type: "text" },
      { key: "extension", label: "داخلی برنامهٔ تماس", type: "text" },
    ], credential_fields: [
      { key: "username", label: "نام کاربری مرکز تلفن", type: "secret", required: true },
      { key: "password", label: "رمز مرکز تلفن", type: "secret", required: true },
    ] },
  ],
  test_recipients: [
    { id: 1, label: "مدیر کشیک · نمونه", phone_masked: "+98 912 *** ** 41", consented: true },
    { id: 2, label: "مسئول عملیات · نمونه", phone_masked: "+98 935 *** ** 27", consented: true },
  ],
};

function previewError(status: number, message: string): Error & { status: number } {
  return Object.assign(new Error(message), { status });
}

/** A separate development entry uses this in-memory client; it has no network transport. */
export function createCommunicationsPreviewClient(): CommunicationsClient {
  if (!import.meta.env.DEV) throw new Error("Preview client is only available in development");
  let snapshot = structuredClone(initialSnapshot);
  let events: DeliveryEvent[] = [
    { id: 1, channel: "sms", recipient_label: "مدیر کشیک · نمونه", phone_masked: "+98 912 *** ** 41", status: "dry_run", created_at: "2026-10-21T09:00:00Z", provider_reference: null },
  ];
  const requests = new Map<string, { event_id: number; status: string; dry_run: true }>();
  let nextRecipient = 3;
  let nextEvent = 2;

  function changed(body: Record<string, unknown>, currentVersion: number): number {
    if (body.expected_version !== currentVersion) throw previewError(409, "Preview version changed");
    return currentVersion + 1;
  }

  async function request(method: string, path: string, raw?: unknown, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted();
    const body = (raw ?? {}) as Record<string, unknown>;
    const endpoint = path.split("?")[0];
    if (method === "GET" && endpoint === "/communications") return structuredClone(snapshot);
    if (method === "GET" && endpoint === "/communications/deliveries") {
      const query = new URLSearchParams(path.split("?")[1]);
      const offset = Math.max(0, Number(query.get("offset")) || 0);
      const limit = Math.min(200, Math.max(1, Number(query.get("limit")) || 50));
      return { items: structuredClone(events.slice(offset, offset + limit)), total: events.length };
    }
    if (method === "GET" && endpoint === "/communications/test-recipients") return { items: structuredClone(snapshot.test_recipients) };
    if (method === "PUT" && /^\/communications\/channels\/(sms|voip)$/.test(endpoint)) {
      const channel = endpoint.split("/").at(-1) as CommunicationChannel;
      const previous = snapshot.channels[channel];
      const providerId = String(body.provider_id);
      const provider = snapshot.provider_catalog.find((item) => item.id === providerId && item.channels.includes(channel));
      if (providerId !== "none" && !provider) throw previewError(422, "Unknown preview provider");
      const action = String(body.secret_action ?? "keep");
      if (action === "keep" && providerId !== previous.provider_id && previous.credentials.configured) throw previewError(422, "Replacement credentials required");
      const configured = action === "replace" ? true : action === "clear" ? false : previous.credentials.configured;
      if (body.enabled && (!configured || !provider)) throw previewError(422, "Preview channel needs configuration");
      const version = changed(body, previous.version);
      snapshot.channels[channel] = { version, provider_id: providerId, enabled: Boolean(body.enabled) && action !== "clear", ready: Boolean(body.enabled && provider && configured && action !== "clear"),
        config: structuredClone(body.config ?? {}) as Record<string, string>, credentials: { configured, masked: configured ? "••••••••" : null } };
      return structuredClone(snapshot);
    }
    if (method === "PUT" && endpoint === "/communications/call-policy") {
      if (body.enabled && !snapshot.channels.voip.ready) throw previewError(422, "Configure the call channel first");
      const version = changed(body, snapshot.call_policy.version);
      const { expected_version: _version, confirmation: _confirmation, ...policy } = body;
      snapshot.call_policy = { ...structuredClone(policy), version } as unknown as CommunicationsSnapshot["call_policy"];
      return structuredClone(snapshot);
    }
    if (method === "POST" && endpoint === "/communications/test-recipients") {
      if (!body.consent_confirmed) throw previewError(422, "Consent required");
      const phone = String(body.phone ?? "");
      const recipient: TestRecipient = { id: nextRecipient++, label: String(body.label).slice(0, 80), phone_masked: `+98 *** *** ${phone.slice(-4)}`, consented: true };
      snapshot.test_recipients.push(recipient);
      return structuredClone(recipient);
    }
    if (method === "DELETE" && /^\/communications\/test-recipients\/\d+$/.test(endpoint)) {
      const id = Number(endpoint.split("/").at(-1));
      snapshot.test_recipients = snapshot.test_recipients.filter((item) => item.id !== id);
      return null;
    }
    if (method === "POST" && endpoint === "/communications/test-events") {
      if (body.mode !== "dry_run") throw previewError(403, "Real sending is disabled in this preview");
      const id = String(body.client_request_id);
      const previous = requests.get(id);
      if (previous) return structuredClone(previous);
      const recipient = snapshot.test_recipients.find((item) => item.id === body.recipient_id);
      if (!recipient) throw previewError(422, "Select a preview recipient");
      const channel = String(body.channel) as CommunicationChannel;
      if (channel !== "sms" && channel !== "voip") throw previewError(422, "Unknown preview channel");
      const ready = snapshot.channels[channel].enabled && snapshot.channels[channel].ready;
      const blocked = [...(ready ? [] : ["provider_not_ready"]), ...(channel === "voip" && !snapshot.call_policy.enabled ? ["call_policy_disabled"] : [])];
      const event: DeliveryEvent = { id: nextEvent++, channel, recipient_label: recipient.label, phone_masked: recipient.phone_masked,
        status: "dry_run", created_at: new Date().toISOString(), error_code: blocked[0] ?? null, blocked_reasons: blocked, provider_reference: null };
      events.unshift(event);
      const result = { event_id: Number(event.id), status: "dry_run", dry_run: true as const, allowed: blocked.length === 0, blocked_reasons: blocked };
      requests.set(id, result);
      return structuredClone(result);
    }
    throw previewError(403, "This operation is unavailable in the local preview");
  }

  return {
    get: <T,>(path: string, signal?: AbortSignal) => request("GET", path, undefined, signal) as Promise<T>,
    post: <T,>(path: string, body?: unknown) => request("POST", path, body) as Promise<T>,
    put: <T,>(path: string, body: unknown) => request("PUT", path, body) as Promise<T>,
    delete: <T,>(path: string, body?: unknown) => request("DELETE", path, body) as Promise<T>,
  };
}
