import axios from 'axios';

const envApiUrl = import.meta.env.VITE_API_URL;
const cleanApiUrl = envApiUrl ? envApiUrl.replace(/\/$/, '') : 'http://127.0.0.1:8000';
const baseURL = `${cleanApiUrl.replace(/\/api$/, '')}/api/`;

export type SessionCredentials = {
  access_token: string;
  refresh_token: string | null;
};

let sessionCredentials: SessionCredentials | null | undefined;
let credentialsRequest: Promise<SessionCredentials | null> | null = null;
let refreshRequest: Promise<string | null> | null = null;
let expirySignaled = false;

export const getStoredCredentials = async (): Promise<SessionCredentials | null> => {
  if (sessionCredentials !== undefined) return sessionCredentials;
  if (!credentialsRequest) {
    credentialsRequest = window.electronAPI?.auth.getCredentials().catch(() => null) ?? Promise.resolve(null);
  }
  sessionCredentials = await credentialsRequest;
  credentialsRequest = null;
  return sessionCredentials;
};

export const getStoredAccessToken = async (): Promise<string | null> => {
  return (await getStoredCredentials())?.access_token ?? null;
};

export const storeCredentials = async (credentials: SessionCredentials): Promise<void> => {
  if (!window.electronAPI?.auth) throw new Error('Secure credential storage is unavailable');
  await window.electronAPI.auth.setCredentials(credentials);
  sessionCredentials = credentials;
  expirySignaled = false;
};

export const clearCredentials = async (): Promise<void> => {
  sessionCredentials = null;
  credentialsRequest = null;
  await window.electronAPI?.auth.clearCredentials().catch(() => undefined);
};

const refreshAccessToken = async (): Promise<string | null> => {
  if (refreshRequest) return refreshRequest;
  refreshRequest = (async () => {
    const current = await getStoredCredentials();
    if (!current?.refresh_token) return null;
    try {
      const { data } = await axios.post<{ access_token: string; refresh_token?: string | null }>(
        `${baseURL}auth/refresh`,
        { refresh_token: current.refresh_token },
        { headers: { 'Content-Type': 'application/json', 'X-Client-Type': 'desktop' } },
      );
      const rotated: SessionCredentials = {
        access_token: data.access_token,
        refresh_token: data.refresh_token ?? current.refresh_token,
      };
      await storeCredentials(rotated);
      return rotated.access_token;
    } catch {
      return null;
    }
  })().finally(() => {
    refreshRequest = null;
  });
  return refreshRequest;
};

const expireSession = async (): Promise<void> => {
  await clearCredentials();
  if (expirySignaled) return;
  expirySignaled = true;
  window.dispatchEvent(new Event('auth-expired'));
};

export const apiInstance = axios.create({
  baseURL,
  headers: { 'Content-Type': 'application/json' },
});

apiInstance.interceptors.request.use(async (config) => {
  const token = await getStoredAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

apiInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const requestConfig = error.config as (typeof error.config & { _sessionRetry?: boolean }) | undefined;
    const requestUrl = String(requestConfig?.url ?? '');
    const isPublicAuthRequest = /auth\/(signin|signup|refresh|forgot-password|reset-password)/.test(requestUrl);
    const isSignoutRequest = requestUrl.includes('auth/signout');

    if (error.response?.status === 401 && requestConfig && !requestConfig._sessionRetry && !isPublicAuthRequest && !isSignoutRequest) {
      requestConfig._sessionRetry = true;
      const refreshedToken = await refreshAccessToken();
      if (refreshedToken) {
        requestConfig.headers.Authorization = `Bearer ${refreshedToken}`;
        return apiInstance(requestConfig);
      }
      await expireSession();
    } else if (error.response?.status === 401 && requestConfig?._sessionRetry && !isSignoutRequest) {
      await expireSession();
    }

    let message = error.message || 'An unexpected error occurred.';
    if (error.response) {
      const detail = error.response.data?.detail;
      if (typeof detail === 'string') message = detail;
      if (Array.isArray(detail)) {
        message = detail.map((item: { loc?: unknown[]; msg?: string }) => {
          const field = item.loc && item.loc.length > 0 ? item.loc[item.loc.length - 1] : 'request';
          return `${field}: ${item.msg ?? 'invalid'}`;
        }).join(', ');
      }
    }
    throw new Error(message);
  },
);

export type UserProfile = {
  id: number;
  username: string;
  full_name: string;
  email: string;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  refresh_token?: string | null;
  token_type: 'bearer';
  user: UserProfile;
};

export type CurrencyMode = 'usd' | 'toman';
export type PriceTimeframe = '1h' | '24h' | '7d' | '30d' | '1y';
export type OperationalPriceStatus =
  | 'live'
  | 'fresh_cache'
  | 'cached'
  | 'verifying'
  | 'suspicious'
  | 'suspicious_unconfirmed'
  | 'derived_fallback'
  | 'stale'
  | 'expired'
  | 'unpersisted'
  | 'unavailable';

export type AlertCreate = {
  asset: string;
  target_price: number | null;
  alert_type?: 'price' | 'formula';
  formula?: string | null;
  currency_mode: CurrencyMode;
  condition: 'above' | 'below';
  notify_app: boolean;
  notify_email: boolean;
  notify_webhook: boolean;
  webhook_url: string | null;
  enable_dlq: boolean;
};

export type AlertResponse = AlertCreate & {
  id: number;
  alert_type: 'price' | 'formula';
  is_active: boolean;
  created_at: string;
};

export type NotificationPreferences = {
  push_app: boolean;
  sms_enabled: boolean;
  sms_phone: string | null;
  sms_verified: boolean;
  email_enabled: boolean;
  email_address: string | null;
  email_verified: boolean;
  telegram_enabled: boolean;
  telegram_id: string | null;
  telegram_verified: boolean;
  silent_mode: boolean;
  aggressive_alerts: boolean;
  push_available: boolean;
  email_available: boolean;
  sms_available: boolean;
  telegram_available: boolean;
  telegram_deeplink_available: boolean;
};

export type TelegramDeepLink = {
  url: string;
  expires_at: string;
  expires_in_seconds: number;
};

export type NotificationItem = {
  id: number | string;
  title: string;
  message: string;
  created_at: string;
  read_at?: string | null;
  severity?: 'info' | 'success' | 'warning' | 'error';
};

export type SupportTicket = {
  id: number;
  subject: string;
  status: 'open' | 'in_progress' | 'waiting_for_user' | 'answered' | 'resolved' | 'closed';
  date: string;
  last_message: string;
};

export type SupportMessage = {
  id: number;
  ticket_id: number;
  from_user: 'user' | 'admin';
  content: string;
  timestamp: string;
};

export type ChatMessage = { role: 'user' | 'assistant'; content: string };
export type ChatResponse = { session_id?: number; reply: string };
export type ChatSessionSummary = { id: number; title: string; created_at: string; updated_at: string };
export type ChatSessionDetail = ChatSessionSummary & { messages: ChatMessage[] };
export type AnalyzeResponse = { asset: string; analysis: string };

export type PriceAsset = {
  asset: string;
  label_fa: string;
  label_en: string;
  price_usd: number | null;
  price_toman: number | null;
  change_percent: number;
  trend: 'up' | 'down';
  history: PricePoint[];
  source_usd: string;
  source_toman: string;
  usd_status: OperationalPriceStatus;
  toman_status: OperationalPriceStatus;
  stale_minutes: number | null;
  chart_error: boolean;
  chart_error_message: { fa: string; en: string };
  observed_at?: string | null;
  canonical_at?: string | null;
  age_seconds?: number | null;
  source_summary?: string | Record<string, unknown> | null;
  candidate_price_usd?: number | null;
  candidate_price_toman?: number | null;
  candidate_provider?: string | null;
  candidate_observed_at?: string | null;
  difference_percent?: number | null;
  verification_status?: string | null;
};

export type PricePoint = {
  timestamp: string;
  value_usd: number | null;
  value_toman: number | null;
  open?: number | null;
  close?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
};

export type PricesResponse = { refreshed_at: string; source: { usd?: string; toman?: string }; assets: PriceAsset[] };
export type PriceHistoryResponse = { asset: string; points: PricePoint[]; status?: string };

export type InstrumentSourceQuote = {
  id?: number | string;
  provider_id?: string;
  provider_name?: string;
  role?: string;
  price: number | null;
  status?: OperationalPriceStatus | 'rejected';
  observed_at?: string | null;
  age_seconds?: number | null;
  difference_percent?: number | null;
  is_derived?: boolean;
  rejection_reason?: string | null;
};

export type InstrumentSourcesResponse = {
  instrument_id: string;
  status?: OperationalPriceStatus;
  canonical_price?: number | null;
  candidate_price?: number | null;
  candidate_provider?: string | null;
  difference_percent?: number | null;
  verification_status?: string | null;
  sources: InstrumentSourceQuote[];
};

export type InstrumentSummary = {
  instrument_id: string;
  base_asset: string;
  quote_currency: string;
  market?: string;
  region?: string;
  weight_unit?: string | null;
  purity?: string | number | null;
  display_decimals?: number;
  price?: number | null;
  canonical_price?: number | null;
  candidate_price?: number | null;
  status?: OperationalPriceStatus;
  source_summary?: string | Record<string, unknown> | null;
  observed_at?: string | null;
  canonical_at?: string | null;
  age_seconds?: number | null;
};

export const api = {
  auth: {
    async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
      return (await apiInstance.post<AuthResponse>('auth/signin', credentials, { headers: { 'X-Client-Type': 'desktop' } })).data;
    },
    async signup(payload: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
      return (await apiInstance.post<AuthResponse>('auth/signup', payload, { headers: { 'X-Client-Type': 'desktop' } })).data;
    },
    async me(): Promise<UserProfile> {
      return (await apiInstance.get<UserProfile>('auth/me')).data;
    },
    async forgotPassword(email: string): Promise<void> {
      await apiInstance.post('auth/forgot-password', { email });
    },
    async resetPassword(payload: { email: string; code: string; new_password: string }): Promise<void> {
      await apiInstance.post('auth/reset-password', payload);
    },
    async changePassword(payload: { current_password: string; new_password: string }): Promise<void> {
      await apiInstance.post('auth/change-password', payload);
    },
    async signout(): Promise<void> {
      await apiInstance.post('auth/signout');
    },
  },
  alerts: {
    async list(): Promise<AlertResponse[]> { return (await apiInstance.get<AlertResponse[]>('alerts')).data; },
    async create(payload: AlertCreate): Promise<AlertResponse> { return (await apiInstance.post<AlertResponse>('alerts', payload)).data; },
    async remove(id: number): Promise<void> { await apiInstance.delete(`alerts/${id}`); },
  },
  notifications: {
    async list(): Promise<NotificationItem[]> {
      const { data } = await apiInstance.get<NotificationItem[] | { items?: NotificationItem[]; notifications?: NotificationItem[] }>('notifications');
      if (Array.isArray(data)) return data;
      return data.notifications ?? data.items ?? [];
    },
    async markRead(id: number | string): Promise<NotificationItem> {
      return (await apiInstance.patch<NotificationItem>(`notifications/${encodeURIComponent(String(id))}/read`)).data;
    },
    async readAll(): Promise<void> { await apiInstance.post('notifications/read-all'); },
    async preferences(): Promise<NotificationPreferences> { return (await apiInstance.get<NotificationPreferences>('notifications/preferences')).data; },
    async setBasic(key: 'push_app' | 'silent_mode' | 'aggressive_alerts', enabled: boolean): Promise<NotificationPreferences> {
      return (await apiInstance.patch<NotificationPreferences>(`notifications/preferences/${key}`, { enabled })).data;
    },
    async startOtp(channel: 'sms' | 'email', destination: string): Promise<{ message: string; destination: string; ttl_minutes: number }> {
      return (await apiInstance.post('notifications/otp/start', { channel, destination })).data;
    },
    async confirmOtp(channel: 'sms' | 'email', destination: string, code: string): Promise<NotificationPreferences> {
      return (await apiInstance.post<NotificationPreferences>('notifications/otp/confirm', { channel, destination, code })).data;
    },
    async setTelegram(telegram_id: string): Promise<NotificationPreferences> {
      return (await apiInstance.post<NotificationPreferences>('notifications/telegram', { telegram_id })).data;
    },
    async confirmTelegram(code: string): Promise<NotificationPreferences> {
      return (await apiInstance.post<NotificationPreferences>('notifications/telegram/confirm', { code })).data;
    },
    async createTelegramDeepLink(): Promise<TelegramDeepLink> {
      return (await apiInstance.post<TelegramDeepLink>('notifications/telegram/deep-link')).data;
    },
    async disable(channel: 'sms' | 'email' | 'telegram'): Promise<NotificationPreferences> {
      return (await apiInstance.delete<NotificationPreferences>(`notifications/${channel}`)).data;
    },
  },
  support: {
    async listTickets(): Promise<SupportTicket[]> { return (await apiInstance.get<SupportTicket[]>('support/tickets')).data; },
    async createTicket(payload: { subject: string; message: string }): Promise<SupportTicket> {
      return (await apiInstance.post<SupportTicket>('support/ticket', payload)).data;
    },
    async listMessages(ticketId: number): Promise<SupportMessage[]> {
      return (await apiInstance.get<SupportMessage[]>(`support/ticket/${ticketId}/messages`)).data;
    },
    async sendMessage(ticketId: number, content: string): Promise<SupportMessage> {
      return (await apiInstance.post<SupportMessage>(`support/ticket/${ticketId}/message`, { content })).data;
    },
  },
  insights: {
    async analyze(asset: string, language: 'fa' | 'en'): Promise<AnalyzeResponse> {
      return (await apiInstance.post<AnalyzeResponse>('insights/analyze', { asset, language })).data;
    },
    async chat(messages: ChatMessage[], language: 'fa' | 'en', session_id?: number | null): Promise<ChatResponse> {
      return (await apiInstance.post<ChatResponse>('insights/chat', { messages, language, session_id })).data;
    },
    async listSessions(): Promise<ChatSessionSummary[]> { return (await apiInstance.get<ChatSessionSummary[]>('insights/chat/sessions')).data; },
    async getSession(id: number): Promise<ChatSessionDetail> { return (await apiInstance.get<ChatSessionDetail>(`insights/chat/sessions/${id}`)).data; },
    async renameSession(id: number, title: string): Promise<ChatSessionSummary> {
      return (await apiInstance.patch<ChatSessionSummary>(`insights/chat/sessions/${id}`, { title })).data;
    },
    async deleteSession(id: number): Promise<void> { await apiInstance.delete(`insights/chat/sessions/${id}`); },
  },
  instruments: {
    async list(): Promise<InstrumentSummary[]> {
      const { data } = await apiInstance.get<InstrumentSummary[] | { instruments?: InstrumentSummary[]; items?: InstrumentSummary[] }>('instruments');
      if (Array.isArray(data)) return data;
      return data.instruments ?? data.items ?? [];
    },
    async get(id: string): Promise<InstrumentSummary> { return (await apiInstance.get<InstrumentSummary>(`instruments/${encodeURIComponent(id)}`)).data; },
    async history(id: string, timeframe: PriceTimeframe = '24h'): Promise<{ instrument_id: string; timeframe?: string; status?: string; points: Array<{ timestamp: string; value: number }> }> {
      return (await apiInstance.get(`instruments/${encodeURIComponent(id)}/history`, { params: { timeframe } })).data;
    },
    async sources(id: string): Promise<InstrumentSourcesResponse> {
      const { data } = await apiInstance.get<InstrumentSourcesResponse | InstrumentSourceQuote[] | { data?: InstrumentSourcesResponse }>(`instruments/${encodeURIComponent(id)}/sources`);
      if (Array.isArray(data)) return { instrument_id: id, sources: data };
      const payload = 'data' in data && data.data ? data.data : data as InstrumentSourcesResponse;
      return { ...payload, instrument_id: payload.instrument_id ?? id, sources: Array.isArray(payload.sources) ? payload.sources : [] };
    },
    async sourceHistory(id: string, timeframe: PriceTimeframe = '24h'): Promise<Record<string, unknown>> {
      return (await apiInstance.get(`instruments/${encodeURIComponent(id)}/sources/history`, { params: { timeframe } })).data;
    },
    async verification(id: string): Promise<Record<string, unknown>> {
      return (await apiInstance.get(`instruments/${encodeURIComponent(id)}/verification`)).data;
    },
    async health(id: string): Promise<Record<string, unknown>> {
      return (await apiInstance.get(`instruments/${encodeURIComponent(id)}/health`)).data;
    },
  },
};

export const getPrices = async (signal?: AbortSignal): Promise<PricesResponse> =>
  (await apiInstance.get<PricesResponse>('prices', { signal })).data;

export const getPriceHistory = async (asset: string, timeframe: PriceTimeframe = '24h', signal?: AbortSignal): Promise<PriceHistoryResponse> =>
  (await apiInstance.get<PriceHistoryResponse>(`prices/${asset}/history`, { params: { timeframe }, signal })).data;

export const getPricesWebSocketUrl = (): string => {
  const url = new URL(baseURL);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/api\/?$/, '').replace(/\/$/, '')}/api/ws/prices`;
  url.search = '';
  return url.toString();
};

export const formatPrice = (value: number | null | undefined, mode: CurrencyMode, language: 'en' | 'fa' = 'en'): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return new Intl.NumberFormat(language === 'fa' ? 'fa-IR' : 'en-US', {
    minimumFractionDigits: mode === 'usd' ? 2 : 0,
    maximumFractionDigits: mode === 'usd' ? 2 : 0,
  }).format(value);
};
