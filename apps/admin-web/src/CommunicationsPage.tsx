import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import "./communications.css";

export type CommunicationChannel = "sms" | "voip";
export interface CommunicationsClient {
  get<T = unknown>(path: string, signal?: AbortSignal): Promise<T>;
  post<T = unknown>(path: string, body?: unknown): Promise<T>;
  put<T = unknown>(path: string, body: unknown): Promise<T>;
  delete?<T = unknown>(path: string, body?: unknown): Promise<T>;
}
export interface ProviderField { key: string; label: string; type: "text" | "url" | "secret"; required?: boolean }
export interface CommunicationProvider {
  id: string; label: string; channels: CommunicationChannel[];
  config_fields: ProviderField[]; credential_fields: ProviderField[];
}
export interface ChannelConfiguration {
  version: number; enabled: boolean; provider_id: string; ready: boolean; config: Record<string, string>;
  credentials: { configured: boolean; masked: string | null };
}
export interface CallPolicy {
  version: number; enabled: boolean; critical_only: boolean; persist_seconds: number; max_attempts: number;
  cooldown_seconds: number; max_calls_per_day: number;
  quiet_hours: { enabled: boolean; start: string; end: string; timezone: string; critical_bypass: boolean };
}
export interface TestRecipient { id: number; label: string; phone_masked: string; consented: boolean; created_at?: string }
export interface DeliveryEvent {
  id: number | string; channel: CommunicationChannel; recipient_label: string; phone_masked: string;
  status: string; created_at: string; error_code?: string | null; provider_reference?: string | null; blocked_reasons?: string[];
}
export interface CommunicationTestResult { event_id: number | string; status: string; dry_run: boolean; blocked_reasons?: string[]; reasons?: string[] }
export interface CommunicationsSnapshot {
  version: number; encryption_ready: boolean; channels: Record<CommunicationChannel, ChannelConfiguration>;
  call_policy: CallPolicy; provider_catalog: CommunicationProvider[]; test_recipients: TestRecipient[];
}
export interface CommunicationsPageProps {
  permissions: string[]; refreshKey: number; client: CommunicationsClient; demo?: boolean;
}
type Draft = Pick<ChannelConfiguration, "enabled" | "provider_id" | "config">;
type Approval = { title: string; impact: string; confirmation: string; execute: () => Promise<void> };
type Tab = "conditions" | "recipients" | "history";
const BASE = "/communications";
const HISTORY_PAGE_SIZE = 50;
const channelName: Record<CommunicationChannel, string> = { sms: "پیامک", voip: "تماس" };
const faNumber = (value: number) => new Intl.NumberFormat("fa-IR").format(value);
const statusLabels: Record<string, string> = {
  dry_run: "ارزیابی بدون ارسال", queued: "در صف", sending: "در حال ارسال", accepted: "پذیرش سرویس",
  delivered: "دریافت تأیید شده", unknown: "نتیجه نامشخص", failed: "ناموفق", cancelled: "لغو شده",
};
const reasonLabels: Record<string, string> = {
  channel_disabled: "این کانال خاموش است.", provider_not_ready: "پیکربندی سرویس آماده نیست.",
  provider_unconfigured: "سرویس هنوز تنظیم نشده است.", credentials_missing: "کلید سرویس ثبت نشده است.",
  encryption_not_ready: "نگهداری امن کلید آماده نیست.", recipient_not_consented: "رضایت صاحب شماره ثبت نشده است.",
  recipient_not_found: "شمارهٔ آزمون پیدا نشد.", quiet_hours: "اکنون در ساعت سکوت هستیم.",
  policy_disabled: "قانون تماس خاموش است.", call_policy_disabled: "قانون تماس خاموش است.",
  cooldown: "فاصلهٔ لازم از تماس قبلی نگذشته است.", daily_cap: "سقف تماس روزانه پر شده است.",
  daily_limit: "سقف تماس روزانه پر شده است.", max_attempts: "تعداد تلاش مجاز این هشدار تمام شده است.",
  not_critical: "این هشدار بحرانی نیست.", persist_not_met: "شرط هنوز به اندازهٔ کافی پایدار نمانده است.",
  provider_error: "سرویس درخواست را نپذیرفت.", transport_error: "ارتباط با سرویس کامل نشد.",
  channel_revoked: "اجازهٔ این کانال برای هشدار برداشته شده است.",
  owner_or_alert_unavailable: "حساب یا هشدار دیگر فعال و در دسترس نیست.",
  worker_completion_unknown: "تأیید نهایی ارسال ثبت نشده است؛ دریافت مخاطب معلوم نیست.",
  provider_dns_unavailable: "نشانی سرویس اکنون در دسترس نیست.",
  provider_disabled: "سرویس خاموش یا آماده نیست.", provider_rejected: "سرویس درخواست را نپذیرفت.",
  provider_result_unknown: "نتیجهٔ سرویس روشن نیست؛ ارسال دوباره خودکار انجام نمی‌شود.",
  recipient_removed: "شماره از فهرست آزمون حذف شده است.", recipient_revoked_or_changed: "شماره یا اجازهٔ مخاطب تغییر کرده است.",
  recipient_or_consent_unavailable: "شماره یا رضایت مخاطب در دسترس نیست.",
  daily_call_cap: "سقف تماس روزانه پر شده است.", call_cooldown: "فاصلهٔ لازم از تماس قبلی نگذشته است.",
  call_attempt_cap: "تعداد تلاش مجاز این هشدار تمام شده است.", critical_alert_required: "تماس فقط برای هشدار بحرانی مجاز است.",
  call_policy_invalid: "شرایط تماس نیاز به اصلاح دارد.", delivery_preflight_failed: "بررسی پیش از ارسال کامل نشد.",
  price_or_source_unavailable: "قیمت تازه یا اجازهٔ مصرف منبع در دسترس نیست.", condition_cleared_or_price_stale: "شرط هشدار رفع شده یا قیمت کهنه است.",
  alert_condition_changed: "شرط هشدار پس از ثبت درخواست تغییر کرده است.",
};
const explainReason = (code: string) => reasonLabels[code] ?? "درخواست با یکی از پیش‌نیازهای ارسال سازگار نیست؛ تنظیمات و شرایط را بررسی کنید.";
const fieldLabels: Record<string, string> = { sender: "خط ارسال پیامک", template_id: "نام الگوی تأیید شماره", endpoint: "نشانی امن سرویس تماس", trunk: "مسیر خروجی تماس", ari_app: "نام برنامهٔ تماس", caller_id: "شمارهٔ تماس‌گیرنده", context: "زمینهٔ شماره‌گیری", extension: "داخلی مقصد", api_key: "کلید دسترسی", username: "نام کاربری سرویس", password: "رمز سرویس" };
const fieldLabel = (field: ProviderField) => fieldLabels[field.key] ?? field.label;
const emptyDrafts: Record<CommunicationChannel, Draft> = {
  sms: { enabled: false, provider_id: "none", config: {} }, voip: { enabled: false, provider_id: "none", config: {} },
};
const copyPolicy = (policy: CallPolicy): CallPolicy => ({ ...policy, quiet_hours: { ...policy.quiet_hours } });
function safeError(reason: unknown, write = false): string {
  const status = typeof reason === "object" && reason && "status" in reason ? Number(reason.status) : 0;
  if (status === 409) return "تنظیمات توسط فرد دیگری تغییر کرده‌اند. ابتدا بازخوانی کنید.";
  if (status === 401 || status === 403) return "دسترسی یا تأیید هویت شما کافی نیست. دوباره وارد شوید.";
  if (status === 422) return "اطلاعات فرم پذیرفته نشد. فیلدها و پیش‌نیازهای سرویس را بررسی کنید.";
  return write ? "نتیجه درخواست روشن نیست. پیش از تلاش دوباره، وضعیت را بازخوانی کنید." : "دریافت اطلاعات انجام نشد. دوباره بازخوانی کنید.";
}
function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("fa-IR", { dateStyle: "short", timeStyle: "short" }).format(date);
}
function Icon({ kind }: { kind: "sms" | "voip" | "shield" | "arrow" }) {
  const paths = {
    sms: "M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-6 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm2 5h10M7 13h6",
    voip: "M5 3h4l2 5-3 2a15 15 0 0 0 6 6l2-3 5 2v4a2 2 0 0 1-2 2C10 21 3 14 3 5a2 2 0 0 1 2-2Z",
    shield: "m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6l8-3Zm-4 9 3 3 5-6",
    arrow: "M18 12H6m5-5-5 5 5 5",
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]} /></svg>;
}

export function CommunicationsPage({ permissions, refreshKey, client, demo = false }: CommunicationsPageProps) {
  const prefix = useId();
  const canRead = permissions.includes("admin.settings.read");
  const canManage = permissions.includes("admin.settings.manage");
  const canTest = permissions.includes("admin.alerts.manage");
  const canReadHistory = permissions.includes("admin.alerts.read");
  const [snapshot, setSnapshot] = useState<CommunicationsSnapshot | null>(null);
  const [drafts, setDrafts] = useState(emptyDrafts);
  const [secrets, setSecrets] = useState<Record<CommunicationChannel, Record<string, string>>>({ sms: {}, voip: {} });
  const [policy, setPolicy] = useState<CallPolicy | null>(null);
  const [channel, setChannel] = useState<CommunicationChannel>("sms");
  const [tab, setTab] = useState<Tab>("conditions");
  const [events, setEvents] = useState<DeliveryEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [readError, setReadError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [writeNeedsReload, setWriteNeedsReload] = useState(false);
  const [testResult, setTestResult] = useState<CommunicationTestResult | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [recipientLabel, setRecipientLabel] = useState("");
  const [recipientPhone, setRecipientPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [selectedRecipient, setSelectedRecipient] = useState("");
  const [approval, setApproval] = useState<Approval | null>(null);
  const alive = useRef(true);
  const generation = useRef(0);
  const activeRead = useRef<AbortController | null>(null);
  const activeHistoryRead = useRef<AbortController | null>(null);
  const historyGeneration = useRef(0);
  const historyOffsetRef = useRef(0);
  historyOffsetRef.current = historyOffset;
  const writing = useRef(false);
  const uncertainWrite = useRef(false);

  const reload = useCallback(async () => {
    const current = ++generation.current;
    activeRead.current?.abort();
    if (!canRead) { setLoading(false); return false; }
    const controller = new AbortController();
    activeRead.current = controller;
    setLoading(true); setReadError("");
    const [state] = await Promise.allSettled([
      client.get<CommunicationsSnapshot>(BASE, controller.signal),
    ]);
    if (!alive.current || controller.signal.aborted || current !== generation.current) return false;
    let loaded = false;
    if (state.status === "fulfilled") {
      const next = state.value;
      setSnapshot(next);
      setDrafts({ sms: { ...next.channels.sms, config: { ...next.channels.sms.config } }, voip: { ...next.channels.voip, config: { ...next.channels.voip.config } } });
      setPolicy(copyPolicy(next.call_policy)); setSecrets({ sms: {}, voip: {} }); setFieldErrors({});
      setWriteNeedsReload(false);
      uncertainWrite.current = false;
      setSelectedRecipient((value) => next.test_recipients.some((item) => String(item.id) === value) ? value : "");
      loaded = true;
    } else setReadError(safeError(state.reason));
    setLoading(false);
    return loaded;
  }, [client, canRead]);

  const loadHistory = useCallback(async (offset = historyOffsetRef.current) => {
    const current = ++historyGeneration.current;
    activeHistoryRead.current?.abort();
    if (!alive.current) return;
    if (!canReadHistory || !canRead) { setEvents([]); setHistoryTotal(0); setHistoryLoading(false); return; }
    const controller = new AbortController();
    activeHistoryRead.current = controller;
    setHistoryLoading(true); setHistoryError("");
    try {
      const result = await client.get<{ items: DeliveryEvent[]; total: number }>(`${BASE}/deliveries?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`, controller.signal);
      if (!alive.current || controller.signal.aborted || current !== historyGeneration.current) return;
      const total = Math.max(0, Number(result.total) || 0);
      setEvents(result.items); setHistoryTotal(total);
      if (offset > 0 && offset >= total) setHistoryOffset(total ? Math.floor((total - 1) / HISTORY_PAGE_SIZE) * HISTORY_PAGE_SIZE : 0);
    } catch (reason) {
      if (alive.current && !controller.signal.aborted && current === historyGeneration.current) setHistoryError(safeError(reason));
    } finally {
      if (alive.current && !controller.signal.aborted && current === historyGeneration.current) setHistoryLoading(false);
    }
  }, [client, canRead, canReadHistory]);

  useEffect(() => {
    alive.current = true; void reload();
    return () => { alive.current = false; generation.current++; activeRead.current?.abort(); };
  }, [reload, refreshKey]);
  useEffect(() => {
    void loadHistory(historyOffset);
    return () => { historyGeneration.current++; activeHistoryRead.current?.abort(); };
  }, [loadHistory, historyOffset, refreshKey]);
  useEffect(() => { setFieldErrors({}); setError(""); }, [channel, tab]);

  const run = async (operation: () => Promise<void>, success: string) => {
    if (writing.current || uncertainWrite.current || readError || loading) return false;
    writing.current = true; setBusy(true); setError(""); setNotice("");
    try {
      await operation();
      if (alive.current) {
        setNotice(success);
        await reload();
        void loadHistory();
      }
      return true;
    } catch (reason) {
      if (alive.current) {
        setError(safeError(reason, true));
        const status = typeof reason === "object" && reason && "status" in reason ? Number(reason.status) : 0;
        if (status === 0 || status === 408 || status === 409 || status >= 500) { uncertainWrite.current = true; setWriteNeedsReload(true); }
      }
      return false;
    }
    finally { writing.current = false; if (alive.current) setBusy(false); }
  };
  const setDraft = (patch: Partial<Draft>) => setDrafts((values) => ({ ...values, [channel]: { ...values[channel], ...patch } }));
  const setPolicyField = (patch: Partial<CallPolicy>) => setPolicy((value) => value ? { ...value, ...patch } : value);
  const setQuiet = (patch: Partial<CallPolicy["quiet_hours"]>) => setPolicy((value) => value ? { ...value, quiet_hours: { ...value.quiet_hours, ...patch } } : value);
  const provider = snapshot?.provider_catalog.find((item) => item.id === drafts[channel].provider_id);
  const current = snapshot?.channels[channel];
  const draft = drafts[channel];
  const configuredForDraft = current?.provider_id === draft.provider_id && current.credentials.configured;
  const providerDirty = Boolean(current && (draft.provider_id !== current.provider_id || draft.enabled !== current.enabled || JSON.stringify(draft.config) !== JSON.stringify(current.config) || Object.values(secrets[channel]).some((value) => value.trim())));
  const recipients = snapshot?.test_recipients ?? [];
  const selected = recipients.find((item) => String(item.id) === selectedRecipient);
  const locked = busy || loading || Boolean(readError) || writeNeedsReload;

  function saveProvider(event: FormEvent) {
    event.preventDefault();
    if (!snapshot || !canManage || locked) return;
    const invalid: Record<string, string> = {};
    for (const field of provider?.config_fields ?? []) if (field.required && !String(draft.config[field.key] ?? "").trim()) invalid[`config-${field.key}`] = `${fieldLabel(field)} را وارد کنید.`;
    if (provider?.id === "asterisk_ari") {
      try {
        const address = new URL(draft.config.endpoint ?? "");
        if (address.protocol !== "https:" || address.username || address.password) invalid["config-endpoint"] = "نشانی HTTPS را بدون نام کاربری و رمز وارد کنید.";
      } catch { invalid["config-endpoint"] = "نشانی کامل HTTPS مرکز تلفن را وارد کنید."; }
      const { ari_app: app, context, extension } = draft.config;
      if (!((app && !context && !extension) || (!app && context && extension))) invalid.provider = "برای مسیر تماس، نام برنامه را وارد کنید؛ یا زمینه و داخلی را با هم پر کنید.";
    }
    const provided = Object.values(secrets[channel]).some((value) => value.trim());
    if (provided) for (const field of provider?.credential_fields ?? []) if (field.required && !secrets[channel][field.key]?.trim()) invalid[`secret-${field.key}`] = `${fieldLabel(field)} را هم وارد کنید.`;
    if (draft.enabled && (draft.provider_id === "none" || !provider)) invalid.provider = "ابتدا یک سرویس انتخاب کنید.";
    if (draft.provider_id !== "none" && draft.provider_id !== current?.provider_id && !provided) invalid.secret = "برای سرویس جدید، اطلاعات دسترسی تازه وارد کنید.";
    if (draft.enabled && !configuredForDraft && !provided) invalid.secret = "برای فعال‌سازی، اطلاعات دسترسی سرویس لازم است.";
    if ((provided || draft.enabled) && !snapshot.encryption_ready) invalid.secret = "نگهداری امن کلید در سرور آماده نیست.";
    setFieldErrors(invalid);
    if (Object.keys(invalid).length) return;
    if (draft.provider_id === "none" && current?.credentials.configured) { setFieldErrors({ provider: "ابتدا کلید سرویس فعلی را حذف کنید." }); return; }
    const body = { expected_version: current?.version ?? 0, provider_id: draft.provider_id, enabled: draft.enabled,
      config: { ...draft.config }, secret_action: provided ? "replace" : "keep",
      ...(provided ? { secret_value: { ...secrets[channel] } } : {}),
      ...(draft.enabled ? { confirmation: `ENABLE ${channel.toUpperCase()}` } : {}) };
    const execute = async () => {
        try { await client.put(`${BASE}/channels/${channel}`, body); }
        finally { if (alive.current) setSecrets({ sms: {}, voip: {} }); }
      };
    const onlyDisable = !draft.enabled && current?.enabled && draft.provider_id === current.provider_id && JSON.stringify(draft.config) === JSON.stringify(current.config) && !provided;
    if (onlyDisable) { void run(execute, "کانال خاموش شد."); return; }
    setApproval({ title: `ذخیرهٔ سرویس ${channelName[channel]}`, impact: draft.enabled ? "این کانال برای ارسال‌های مجاز فعال می‌شود. ذخیرهٔ تنظیمات، پیام آزمون ارسال نمی‌کند." : "تنظیمات اتصال ذخیره می‌شود. هیچ پیام آزمونی ارسال نمی‌شود.",
      confirmation: draft.enabled ? `ENABLE ${channel.toUpperCase()}` : "", execute });
  }

  function clearSecret() {
    if (!snapshot || !current || !canManage || locked || !current.credentials.configured) return;
    const confirmation = `CLEAR ${channel.toUpperCase()} SECRET`;
    const body = { expected_version: current.version, provider_id: current.provider_id, config: { ...current.config }, enabled: false, secret_action: "clear", confirmation };
    setApproval({ title: "حذف کلید ذخیره‌شده", impact: `کلید سرویس ${channelName[channel]} حذف و این کانال خاموش می‌شود. برای فعال‌سازی دوباره، کلید جدید لازم است.`, confirmation, execute: async () => {
      try { await client.put(`${BASE}/channels/${channel}`, body); }
      finally { if (alive.current) setSecrets({ sms: {}, voip: {} }); }
    } });
  }

  function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!snapshot || !policy || !canManage || locked) return;
    const invalid: Record<string, string> = {};
    for (const [key, min, max] of [["persist_seconds", 0, 3600], ["max_attempts", 1, 1], ["cooldown_seconds", 30, 86400], ["max_calls_per_day", 1, 100]] as const) {
      const value = policy[key];
      if (!Number.isInteger(value) || value < min || value > max) invalid[key] = `عددی بین ${faNumber(min)} و ${faNumber(max)} وارد کنید.`;
    }
    if (policy.quiet_hours.enabled && policy.quiet_hours.start === policy.quiet_hours.end) invalid.quiet = "شروع و پایان ساعت سکوت باید متفاوت باشند.";
    setFieldErrors(invalid);
    if (Object.keys(invalid).length) return;
    const { version, ...values } = copyPolicy(policy);
    const body = { ...values, expected_version: version, ...(policy.enabled ? { confirmation: "ENABLE VOIP POLICY" } : {}) };
    const execute = () => client.put(`${BASE}/call-policy`, body).then(() => undefined);
    setApproval({ title: policy.enabled ? "فعال‌سازی شرایط تماس" : "ذخیرهٔ شرایط تماس", impact: policy.enabled ? "تماس خودکار فقط با سرویس فعال، شمارهٔ مجاز و شرایط ذخیره‌شده انجام می‌شود." : "قانون تماس خاموش ذخیره می‌شود. هیچ تماس آزمونی ثبت نمی‌شود.", confirmation: policy.enabled ? "ENABLE VOIP POLICY" : "", execute });
  }

  function addRecipient(event: FormEvent) {
    event.preventDefault();
    if (!canManage || locked) return;
    const phone = recipientPhone.replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit))).replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit))).replace(/[\s()-]/g, "");
    const invalid: Record<string, string> = {};
    if (!recipientLabel.trim()) invalid.label = "نام مخاطب را وارد کنید.";
    if (!/^(?:\+98|0)9\d{9}$/.test(phone)) invalid.phone = "شمارهٔ همراه ایران را با ۰۹ یا ‎+۹۸ وارد کنید.";
    if (!consent) invalid.consent = "رضایت صاحب شماره برای آزمون لازم است.";
    setFieldErrors(invalid);
    if (Object.keys(invalid).length) return;
    const label = recipientLabel.trim();
    setApproval({ title: "ثبت شمارهٔ آزمون", impact: "شماره با رضایت صاحب آن در فهرست آزمون ذخیره می‌شود. ثبت شماره، پیامک یا تماس ارسال نمی‌کند.", confirmation: "", execute: async () => { await client.post(`${BASE}/test-recipients`, { label, phone, consent_confirmed: true });
      if (alive.current) { setRecipientPhone(""); setRecipientLabel(""); setConsent(false); }
    } });
  }

  function testChannel(real: boolean) {
    if (!canTest || !selected || locked || (real && (demo || providerDirty || !selected.consented || !current?.ready || !current.enabled))) return;
    const body = { recipient_id: selected.id, channel, mode: real ? "send" : "dry_run", client_request_id: crypto.randomUUID(), ...(real ? { confirmation: "SEND TEST" } : {}) };
    const execute = async () => { const result = await client.post<CommunicationTestResult>(`${BASE}/test-events`, body); if (alive.current) setTestResult(result); };
    if (real) setApproval({ title: `ارسال آزمون ${channelName[channel]}`, impact: `یک ${channelName[channel]} واقعی برای ${selected.label} (${selected.phone_masked}) ثبت می‌شود. پذیرش سرویس به معنی دریافت مخاطب نیست.`, confirmation: "SEND TEST", execute });
    else void run(execute, "ارزیابی ثبت شد؛ هیچ پیامک یا تماسی ارسال نشد.");
  }

  if (!canRead) return <section className="comms comms-access" dir="rtl" lang="fa"><Icon kind="shield" /><h2>دسترسی به تنظیمات ارتباطی ندارید</h2><p>برای مشاهدهٔ این بخش، دسترسی تنظیمات لازم است.</p></section>;

  const field = (key: string, label: string, value: number, min: number, max: number, update: (value: number) => void) => <label className="comms-field" htmlFor={`${prefix}-${key}`}><span>{label}</span><input id={`${prefix}-${key}`} type="number" inputMode="numeric" min={min} max={max} step={1} required value={Number.isNaN(value) ? "" : value} onChange={(event) => update(event.target.value === "" ? NaN : Number(event.target.value))} aria-invalid={Boolean(fieldErrors[key])} aria-describedby={fieldErrors[key] ? `${prefix}-${key}-error` : undefined} /><FieldError id={`${prefix}-${key}-error`} text={fieldErrors[key]} /></label>;

  return <section className="comms" dir="rtl" lang="fa" aria-label="مدیریت پیامک و تماس">
    <header className="comms-heading"><div><span className="comms-eyebrow">ارتباط در لحظه‌های مهم</span><h2>پیامک و تماس</h2><p>مسیر ارتباط را آماده کنید؛ تماس را به شرایط ضروری محدود کنید.</p></div><button className="comms-button comms-button-secondary" type="button" disabled={busy || loading} onClick={() => { void reload(); void loadHistory(); }}>بازخوانی وضعیت</button></header>
    {demo && <div className="comms-demo" role="status"><span className="comms-dot" /><strong>حالت نمایشی</strong><span>تغییرات فقط در حافظهٔ این صفحه‌اند. ارسال واقعی خاموش است.</span></div>}
    {readError && <div className="comms-message comms-message-error" role="alert">{readError}</div>}
    {error && <div className="comms-message comms-message-error" role="alert">{error}</div>}
    {notice && <div className="comms-message comms-message-success" role="status" aria-live="polite">{notice}</div>}
    {loading && !snapshot ? <div className="comms-loading" role="status">در حال دریافت تنظیمات…</div> : snapshot && <>
      <div className="comms-channels" role="group" aria-label="انتخاب کانال">
        {(["sms", "voip"] as const).map((name) => <button key={name} type="button" aria-pressed={channel === name} className={`comms-channel ${channel === name ? "is-selected" : ""}`} onClick={() => setChannel(name)} disabled={busy}>
          <span className="comms-channel-icon"><Icon kind={name} /></span><span className="comms-channel-copy"><strong>{channelName[name]}</strong><span>{name === "sms" ? "هشدار کوتاه برای مخاطب" : "پیگیری شرایط ضروری"}</span></span><span className="comms-channel-state"><span className={`comms-badge ${snapshot.channels[name].ready ? "is-ready" : "is-muted"}`}>{snapshot.channels[name].ready ? "پیکربندی آماده" : "نیاز به تنظیم"}</span><small>{snapshot.channels[name].enabled ? "فعال" : "خاموش"}</small></span>
        </button>)}
      </div>
      <div className="comms-layout">
        <aside className="comms-provider comms-card"><div className="comms-card-heading"><div><span className="comms-eyebrow">اتصال سرویس</span><h3>سرویس {channelName[channel]}</h3></div><span className="comms-icon-small"><Icon kind="shield" /></span></div>
          <ConnectionGuide key={channel} channel={channel} demo={demo} />
          <form onSubmit={saveProvider} className="comms-form">
            <fieldset disabled={!canManage || locked}><label className="comms-field" htmlFor={`${prefix}-provider`}><span>ارائه‌دهنده</span><select id={`${prefix}-provider`} value={draft.provider_id} onChange={(event) => { setDraft({ provider_id: event.target.value, enabled: false, config: {} }); setSecrets((values) => ({ ...values, [channel]: {} })); }}><option value="none">انتخاب نشده</option>{snapshot.provider_catalog.filter((item) => item.channels.includes(channel)).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><FieldError text={fieldErrors.provider} /></label>
              {provider && <p className="comms-help comms-provider-help">{channel === "sms" ? "خط ارسال برای متن هشدار لازم است. الگو اختیاری و فقط برای تأیید شماره است." : "مرکز تلفن باید مسیر تماس آماده داشته باشد. نام برنامه را وارد کنید؛ یا به‌جای آن، زمینه و داخلی را با هم پر کنید."}</p>}
              {(provider?.config_fields ?? []).map((item) => <label key={item.key} className="comms-field" htmlFor={`${prefix}-config-${item.key}`}><span>{fieldLabel(item)}{item.required && <span aria-hidden="true"> *</span>}</span><input id={`${prefix}-config-${item.key}`} type={item.type === "url" ? "url" : "text"} dir={item.type === "url" ? "ltr" : undefined} autoComplete="off" required={item.required} value={draft.config[item.key] ?? ""} onChange={(event) => setDraft({ config: { ...draft.config, [item.key]: event.target.value } })} aria-invalid={Boolean(fieldErrors[`config-${item.key}`])} /><FieldError text={fieldErrors[`config-${item.key}`]} /></label>)}
              {Boolean(provider?.credential_fields.length) && <div className="comms-secret"><div className="comms-secret-status"><span>اطلاعات دسترسی</span><span className={`comms-badge ${configuredForDraft ? "is-ready" : "is-muted"}`}>{configuredForDraft ? "کلید ذخیره شده" : "ثبت نشده"}</span></div>
                {configuredForDraft && <code className="comms-masked" aria-label="کلید ذخیره‌شده پنهان است">••••••••••••</code>}
                {(provider?.credential_fields ?? []).map((item) => <label key={item.key} className="comms-field" htmlFor={`${prefix}-secret-${item.key}`}><span>{fieldLabel(item)}</span><input id={`${prefix}-secret-${item.key}`} type="password" dir="ltr" autoComplete="new-password" spellCheck={false} disabled={!snapshot.encryption_ready} value={secrets[channel][item.key] ?? ""} placeholder={configuredForDraft ? "برای حفظ مقدار فعلی، خالی بگذارید" : "مقدار جدید"} onChange={(event) => setSecrets((values) => ({ ...values, [channel]: { ...values[channel], [item.key]: event.target.value } }))} aria-invalid={Boolean(fieldErrors[`secret-${item.key}`])} /><FieldError text={fieldErrors[`secret-${item.key}`]} /></label>)}
                <p className="comms-help">کلید ذخیره‌شده نمایش داده نمی‌شود. برای تغییر، مقدار جدید را وارد کنید.</p>
              </div>}
              {!snapshot.encryption_ready && <p className="comms-inline-warning">نگهداری امن کلید هنوز آماده نیست؛ ثبت کلید و فعال‌سازی در دسترس نیست.</p>}
              <FieldError text={fieldErrors.secret} />
              <label className="comms-check"><input type="checkbox" checked={draft.enabled} disabled={(!snapshot.encryption_ready && !draft.enabled) || draft.provider_id === "none"} onChange={(event) => setDraft({ enabled: event.target.checked })} /><span><strong>فعال بودن کانال</strong><small>فقط پس از ذخیره و تأیید هویت اعمال می‌شود.</small></span></label>
            </fieldset>
            {canManage ? <><button className="comms-button comms-button-primary" disabled={locked} type="submit">ذخیرهٔ اتصال <Icon kind="arrow" /></button>{current?.credentials.configured && <button type="button" className="comms-remove" onClick={clearSecret} disabled={locked}>حذف کلید ذخیره‌شده</button>}</> : <p className="comms-readonly">دسترسی شما فقط برای مشاهده است.</p>}
          </form>
        </aside>
        <div className="comms-workspace"><div className="comms-tabs" role="group" aria-label="بخش ارتباطات">{([["conditions", "شرایط تماس"], ["recipients", "شماره‌های آزمون"], ["history", "پیگیری ارسال"]] as const).map(([id, label]) => <button key={id} type="button" aria-pressed={tab === id} className={tab === id ? "is-active" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>
          {tab === "conditions" && policy && <form className="comms-card comms-policy" onSubmit={savePolicy}>
            <div className="comms-card-heading"><div><span className="comms-eyebrow">تماس برای شرایط خاص</span><h3>چه زمانی تماس بگیریم؟</h3><p>شدت هشدار، زمان انتظار و سقف تماس را مشخص کنید.</p></div><span className={`comms-badge ${policy.enabled ? "is-ready" : "is-muted"}`}>{policy.enabled ? "قانون فعال" : "قانون خاموش"}</span></div>
            <fieldset disabled={!canManage || locked}><label className="comms-check comms-check-feature"><input type="checkbox" checked={policy.enabled} onChange={(event) => setPolicyField({ enabled: event.target.checked })} /><span><strong>تماس خودکار در شرایط تعیین‌شده</strong><small>کانال تماس و شمارهٔ دارای رضایت هم باید آماده باشند.</small></span></label>
              <div className="comms-form-grid"><label className="comms-field" htmlFor={`${prefix}-severity`}><span>شدت هشدار</span><select id={`${prefix}-severity`} value={policy.critical_only ? "critical" : "all"} onChange={(event) => setPolicyField({ critical_only: event.target.value === "critical" })}><option value="critical">فقط هشدار بحرانی</option><option value="all">همهٔ هشدارهای مجاز</option></select></label>
                {field("persist_seconds", "پایداری شرط · ثانیه", policy.persist_seconds, 0, 3600, (value) => setPolicyField({ persist_seconds: value }))}
                {field("cooldown_seconds", "فاصلهٔ بین تماس‌ها · ثانیه", policy.cooldown_seconds, 30, 86400, (value) => setPolicyField({ cooldown_seconds: value }))}
                <div className="comms-field"><span>تلاش برای هر هشدار</span><strong>یک درخواست؛ بدون تکرار خودکار</strong><p className="comms-help">نتیجهٔ نامشخص دوباره ارسال نمی‌شود؛ از تماس و هزینهٔ تکراری جلوگیری می‌شود.</p></div>
                {field("max_calls_per_day", "سقف تماس در روز", policy.max_calls_per_day, 1, 100, (value) => setPolicyField({ max_calls_per_day: value }))}
              </div>
              <div className="comms-quiet"><label className="comms-check"><input type="checkbox" checked={policy.quiet_hours.enabled} onChange={(event) => setQuiet({ enabled: event.target.checked })} /><span><strong>ساعت سکوت</strong><small>بر اساس ساعت تهران</small></span></label><div className="comms-form-grid comms-time-grid"><label className="comms-field" htmlFor={`${prefix}-quiet-start`}><span>شروع سکوت</span><input id={`${prefix}-quiet-start`} type="time" required dir="ltr" value={policy.quiet_hours.start} disabled={!policy.quiet_hours.enabled} onChange={(event) => setQuiet({ start: event.target.value })} /></label><label className="comms-field" htmlFor={`${prefix}-quiet-end`}><span>پایان سکوت</span><input id={`${prefix}-quiet-end`} type="time" required dir="ltr" value={policy.quiet_hours.end} disabled={!policy.quiet_hours.enabled} onChange={(event) => setQuiet({ end: event.target.value })} /></label></div><FieldError text={fieldErrors.quiet} /><label className="comms-check"><input type="checkbox" checked={policy.quiet_hours.critical_bypass} disabled={!policy.quiet_hours.enabled} onChange={(event) => setQuiet({ critical_bypass: event.target.checked })} /><span>تماس بحرانی در ساعت سکوت مجاز باشد</span></label></div>
            </fieldset>
            <div className="comms-summary"><span className="comms-summary-icon"><Icon kind="voip" /></span><p>{policy.critical_only ? "هشدار بحرانی" : "هشدار مجاز"} پس از <strong>{Number.isFinite(policy.persist_seconds) ? faNumber(policy.persist_seconds) : "—"} ثانیه</strong> پایداری شرط، با سقف <strong>{Number.isFinite(policy.max_calls_per_day) ? faNumber(policy.max_calls_per_day) : "—"} تماس در روز</strong> ارزیابی می‌شود.</p></div>
            {canManage && <div className="comms-actions"><p className="comms-help">ذخیرهٔ قانون، تماس آزمون ایجاد نمی‌کند.</p><button className="comms-button comms-button-primary" type="submit" disabled={locked}>ذخیرهٔ شرایط</button></div>}
          </form>}
          {tab === "recipients" && <div className="comms-card"><div className="comms-card-heading"><div><span className="comms-eyebrow">مخاطب دارای رضایت</span><h3>شماره‌های آزمون</h3><p>فقط شماره‌هایی که خودتان مجاز به آزمون آن‌ها هستید.</p></div><span className="comms-count">{faNumber(recipients.length)} شماره</span></div>
            <div className="comms-recipient-list">{recipients.length ? recipients.map((item) => <article key={item.id} className="comms-recipient"><span className="comms-recipient-avatar">{item.label.slice(0, 1)}</span><div><strong>{item.label}</strong><bdi>{item.phone_masked}</bdi></div><span className={`comms-badge ${item.consented ? "is-ready" : "is-muted"}`}>{item.consented ? "دارای رضایت" : "بدون رضایت"}</span>{canManage && client.delete && <button className="comms-remove" type="button" aria-label={`حذف شمارهٔ ${item.label}`} disabled={locked} onClick={() => setApproval({ title: "حذف شمارهٔ آزمون", impact: `شمارهٔ ${item.label} از فهرست آزمون شما حذف می‌شود.`, confirmation: "", execute: () => client.delete!(`${BASE}/test-recipients/${item.id}`).then(() => undefined) })}>حذف</button>}</article>) : <p className="comms-empty">هنوز شمارهٔ آزمونی ثبت نشده است.</p>}</div>
            {canManage && <form className="comms-recipient-form" onSubmit={addRecipient}><fieldset disabled={locked}><div className="comms-form-grid"><label className="comms-field" htmlFor={`${prefix}-recipient-label`}><span>نام مخاطب</span><input id={`${prefix}-recipient-label`} value={recipientLabel} maxLength={80} required autoComplete="off" onChange={(event) => setRecipientLabel(event.target.value)} aria-invalid={Boolean(fieldErrors.label)} /><FieldError text={fieldErrors.label} /></label><label className="comms-field" htmlFor={`${prefix}-recipient-phone`}><span>شمارهٔ همراه</span><input id={`${prefix}-recipient-phone`} type="tel" dir="ltr" value={recipientPhone} required maxLength={24} autoComplete="off" placeholder="09…" onChange={(event) => setRecipientPhone(event.target.value)} aria-invalid={Boolean(fieldErrors.phone)} /><FieldError text={fieldErrors.phone} /></label></div><label className="comms-check"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>صاحب این شماره برای پیامک یا تماس آزمون رضایت دارد.</span></label><FieldError text={fieldErrors.consent} /></fieldset><button className="comms-button comms-button-secondary" type="submit" disabled={locked}>ثبت شمارهٔ آزمون</button></form>}
          </div>}
          {tab === "history" && <div className="comms-card">
            <div className="comms-card-heading"><div><span className="comms-eyebrow">از درخواست تا دریافت</span><h3>پیگیری ارسال</h3><p>«پذیرش سرویس» با دریافت پیام یا پاسخ‌دادن به تماس متفاوت است.</p></div></div>
            {!canReadHistory ? <p className="comms-empty">دسترسی به تاریخچهٔ ارسال ندارید.</p> : historyLoading ? <p className="comms-empty" role="status">در حال دریافت تاریخچه…</p> : historyError ? <div className="comms-message comms-message-error" role="alert"><p>{historyError}</p><button type="button" className="comms-button comms-button-secondary" onClick={() => void loadHistory()}>تلاش دوبارهٔ تاریخچه</button></div> : events.length ? <div className="comms-table-scroll">
              <table className="comms-table"><caption className="comms-sr-only">آخرین درخواست‌های پیامک و تماس</caption>
                <thead><tr><th scope="col">مخاطب</th><th scope="col">کانال</th><th scope="col">وضعیت</th><th scope="col">زمان</th><th scope="col">شناسهٔ پیگیری</th></tr></thead>
                <tbody>{events.map((item) => <tr key={item.id}>
                  <td><strong>{item.recipient_label}</strong><bdi>{item.phone_masked}</bdi></td><td>{channelName[item.channel] ?? "—"}</td>
                  <td><span className={`comms-badge ${item.status === "delivered" ? "is-ready" : item.status === "failed" ? "is-failed" : "is-muted"}`}>{statusLabels[item.status] ?? "در حال بررسی"}</span>
                    {Boolean(item.error_code || item.blocked_reasons?.length) && <p className="comms-event-reason">{[...new Set([...(item.blocked_reasons ?? []), ...(item.error_code ? [item.error_code] : [])])].map(explainReason).join(" ")}</p>}
                  </td><td>{dateLabel(item.created_at)}</td><td><bdi>{item.provider_reference ?? "—"}</bdi></td>
                </tr>)}</tbody>
              </table>
            </div> : <p className="comms-empty">هنوز درخواست ارسالی ثبت نشده است.</p>}
            {canReadHistory && <nav className="comms-history-pages" aria-label="صفحه‌بندی تاریخچه" aria-busy={historyLoading}>
              <button type="button" className="comms-button comms-button-secondary" disabled={historyOffset === 0} onClick={() => setHistoryOffset((offset) => Math.max(0, offset - HISTORY_PAGE_SIZE))}>قبلی</button>
              <span>{faNumber(historyTotal ? historyOffset + 1 : 0)}–{faNumber(Math.min(historyOffset + HISTORY_PAGE_SIZE, historyTotal))} از {faNumber(historyTotal)}</span>
              <button type="button" className="comms-button comms-button-secondary" disabled={historyOffset + HISTORY_PAGE_SIZE >= historyTotal} onClick={() => setHistoryOffset((offset) => offset + HISTORY_PAGE_SIZE)}>بعدی</button>
            </nav>}
          </div>}
          {canTest && <section className="comms-test comms-card" aria-label="آزمون کانال">
            <div><h3>پیش از استفاده، مسیر را ارزیابی کنید</h3><p>ارزیابی بدون ارسال، پیامک و تماس واقعی ایجاد نمی‌کند.</p></div>
            <div className="comms-test-controls">
              <label className="comms-field" htmlFor={`${prefix}-test-recipient`}><span>شمارهٔ آزمون</span><select id={`${prefix}-test-recipient`} value={selectedRecipient} disabled={locked} onChange={(event) => setSelectedRecipient(event.target.value)}><option value="">مخاطب را انتخاب کنید</option>{recipients.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.phone_masked}</option>)}</select></label>
              <div className="comms-actions"><button className="comms-button comms-button-secondary" type="button" disabled={locked || !selected} onClick={() => testChannel(false)}>ارزیابی بدون ارسال</button><button className="comms-button comms-button-outline" type="button" disabled={locked || demo || providerDirty || !selected?.consented || !current?.ready || !current?.enabled} onClick={() => testChannel(true)}>ارسال آزمون واقعی</button></div>
              <p className="comms-help">{demo ? "ارسال واقعی در نسخهٔ نمایشی در دسترس نیست." : providerDirty ? "ارزیابی بر پایهٔ تنظیمات ذخیره‌شده است؛ برای ارسال واقعی ابتدا اتصال را ذخیره کنید." : "ارسال واقعی به کانال آماده، مخاطب دارای رضایت و تأیید دوبارهٔ هویت نیاز دارد."}</p>
              {testResult && <div className="comms-test-result" role="status" aria-live="polite"><strong>{testResult.dry_run ? "نتیجهٔ ارزیابی بدون ارسال" : "درخواست آزمون ثبت شد"}</strong>{[...(testResult.blocked_reasons ?? testResult.reasons ?? [])].length ? <ul>{(testResult.blocked_reasons ?? testResult.reasons ?? []).map((reason, index) => <li key={`${reason}-${index}`}>{explainReason(reason)}</li>)}</ul> : <p>{testResult.dry_run ? "ارزیابی انجام شد. پیامک یا تماس واقعی ارسال نشده است." : "درخواست در پیگیری ارسال ثبت شد؛ دریافت مخاطب هنوز تأیید نشده است."}</p>}</div>}
            </div>
          </section>}
        </div>
      </div>
    </>}
    {approval && <ApprovalDialog approval={approval} busy={busy} blocked={writeNeedsReload || Boolean(readError) || loading} client={client} demo={demo} onClose={() => { if (!busy) { setApproval(null); setSecrets({ sms: {}, voip: {} }); } }} onConfirm={(operation) => run(operation, "درخواست ثبت شد. آخرین وضعیت را در همین صفحه ببینید.")} onDone={() => setApproval(null)} />}
  </section>;
}

function FieldError({ id, text }: { id?: string; text?: string }) { return text ? <span id={id} className="comms-field-error" role="alert">{text}</span> : null; }

function ConnectionGuide({ channel, demo }: { channel: CommunicationChannel; demo: boolean }) {
  return <details className="comms-setup-guide">
    <summary>راهنمای اتصال {channelName[channel]}</summary>
    {channel === "sms" ? <div>
      <p><strong>کاوه‌نگار:</strong> کلید دسترسی و خط ارسالِ فعال خود را از حساب سرویس بگیرید. کلید را فقط در فیلد کلید دسترسی وارد کنید؛ مقدار ذخیره‌شده نمایش داده نمی‌شود.</p>
      <p>خط ارسال برای متن هشدار لازم است. نام الگوی تأیید شماره اختیاری است و فقط برای کد تأیید شماره به کار می‌رود؛ متن هشدار از خط ارسال فرستاده می‌شود.</p>
    </div> : <div>
      <p><strong>استریسک / ایزابل:</strong> مرکز تلفن باید گواهی معتبر HTTPS، دسترسی ARI و مسیر خروجی تماسِ آماده داشته باشد. نشانی سرویس، ترانک و نام کاربری و رمز ARI را از مسئول مرکز تلفن بگیرید.</p>
      <p>برای مسیر پاسخ، نام برنامهٔ ARI را وارد کنید؛ یا نام برنامه را خالی بگذارید و زمینه و داخلی را با هم پر کنید. برنامه یا مسیر مرکز تلفن باید از پیش برای پاسخ و پخش پیام آماده باشد.</p>
    </div>}
    <ol>
      <li>ارائه‌دهنده، اتصال و اطلاعات دسترسی را وارد و «ذخیرهٔ اتصال» را انتخاب کنید.</li>
      <li>«فعال بودن کانال» را روشن و دوباره ذخیره کنید؛ تأیید هویت و عبارت فعال‌سازی لازم است.{channel === "voip" && " سپس در «شرایط تماس»، قانون، ساعت سکوت و سقف تماس را ذخیره و فعال کنید."}</li>
      <li>در «شماره‌های آزمون»، شمارهٔ مجاز خود را با رضایت صاحب آن ثبت کنید.</li>
      <li>مخاطب را انتخاب و «ارزیابی بدون ارسال» را اجرا کنید؛ علت‌های آماده نبودن را برطرف کنید.</li>
      <li>در صورت نیاز، «ارسال آزمون واقعی» را با تأیید دوبارهٔ هویت و عبارت <bdi>SEND TEST</bdi> انجام دهید؛ این آزمون ممکن است هزینه داشته باشد. نتیجه را در «پیگیری ارسال» ببینید.</li>
    </ol>
    <p className="comms-help">{demo ? "در حالت نمایشی، تنظیمات فقط در حافظهٔ همین صفحه می‌ماند و ارسال واقعی همیشه بسته است." : "ذخیره یا بازکردن راهنما هیچ پیامک و تماسی ارسال نمی‌کند. پذیرش سرویس به معنای دریافت پیام یا پاسخ‌دادن به تماس نیست."}</p>
  </details>;
}

function ApprovalDialog({ approval, busy, blocked, client, demo, onClose, onConfirm, onDone }: {
  approval: Approval; busy: boolean; blocked: boolean; client: CommunicationsClient; demo: boolean; onClose: () => void;
  onConfirm: (operation: () => Promise<void>) => Promise<boolean>; onDone: () => void;
}) {
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || blocked || (!demo && !password) || (approval.confirmation && confirmation !== approval.confirmation)) return;
    setError("");
    const completed = await onConfirm(async () => {
      try { if (!demo) await client.post("/auth/reauthenticate", { password, ...(mfa ? { mfa_code: mfa } : {}) }); await approval.execute(); }
      finally { setPassword(""); setMfa(""); }
    });
    if (completed) onDone();
    else setError("تأیید یا ثبت انجام نشد. اطلاعات ورود را بررسی کنید؛ در صورت قطع ارتباط، ابتدا انصراف دهید و وضعیت را بازخوانی کنید.");
  }
  return <dialog ref={dialog} className="comms-approval" dir="rtl" lang="fa" aria-labelledby={titleId} onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}><form onSubmit={submit}><div className="comms-approval-icon"><Icon kind="shield" /></div><h2 id={titleId}>{approval.title}</h2><p>{approval.impact}</p>{demo && <p className="comms-inline-warning">این تأیید نمایشی است و فقط داده‌های همین صفحه را تغییر می‌دهد.</p>}{error && <div className="comms-message comms-message-error" role="alert">{error}</div>}{!demo && <><label className="comms-field"><span>رمز فعلی مدیر</span><input type="password" value={password} required autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} disabled={busy} /></label><label className="comms-field"><span>کد ورود دومرحله‌ای، اگر فعال است</span><input dir="ltr" value={mfa} autoComplete="one-time-code" onChange={(event) => setMfa(event.target.value)} disabled={busy} /></label></>}{approval.confirmation && <label className="comms-field"><span>برای تأیید، عبارت زیر را وارد کنید</span><code dir="ltr">{approval.confirmation}</code><input dir="ltr" value={confirmation} spellCheck={false} autoComplete="off" required onChange={(event) => setConfirmation(event.target.value)} disabled={busy} /></label>}<div className="comms-actions"><button type="button" className="comms-button comms-button-secondary" onClick={onClose} disabled={busy}>انصراف</button><button type="submit" className="comms-button comms-button-primary" disabled={busy || blocked || (!demo && !password) || Boolean(approval.confirmation && confirmation !== approval.confirmation)}>{busy ? "در حال ثبت…" : "تأیید و ادامه"}</button></div></form></dialog>;
}

export default CommunicationsPage;
