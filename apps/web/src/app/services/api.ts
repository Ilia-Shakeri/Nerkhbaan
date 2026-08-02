import axios from 'axios';

// Use VITE_API_URL when explicitly provided (e.g. local dev pointing at 127.0.0.1:8000).
// In production the Docker nginx container proxies /api/* to the backend, so a relative
// baseURL is correct — the browser resolves it against the current origin automatically.
const envApiUrl = import.meta.env.VITE_API_URL;
let baseURL: string;
if (envApiUrl) {
  const clean = envApiUrl.replace(/\/api\/?$/, '');
  baseURL = `${clean}/api/`;
} else {
  baseURL = '/api/';
}

export const apiInstance = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

let refreshRequest: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (refreshRequest) return refreshRequest;
  refreshRequest = axios
    .post(`${baseURL}auth/refresh`, {}, { withCredentials: true })
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      refreshRequest = null;
    });
  return refreshRequest;
}

apiInstance.interceptors.response.use(
  (response) => {
    window.dispatchEvent(new CustomEvent('api-error-clear', {
      detail: { key: response.config.url || 'unknown' }
    }));
    return response;
  },
  async (error) => {
    const requestConfig = error.config as (typeof error.config & { _sessionRetry?: boolean }) | undefined;
    const requestUrl = String(requestConfig?.url || '');
    const publicAuthRequest = /auth\/(signin|signup|refresh|forgot-password|reset-password)/.test(requestUrl);
    if (error.response?.status === 401 && requestConfig && !requestConfig._sessionRetry && !publicAuthRequest) {
      requestConfig._sessionRetry = true;
      if (await refreshSession()) return apiInstance.request(requestConfig);
    }
    let message = error.message || 'An unexpected error occurred.';
    if (error.response) {
      if (error.response.status === 401) {
        window.dispatchEvent(new Event('auth-expired'));
      }
      try {
        const body = error.response.data;
        if (body?.detail) {
          if (typeof body.detail === 'string') {
            message = body.detail;
          } else if (Array.isArray(body.detail)) {
            message = body.detail.map((err: any) => `${err.loc[err.loc.length - 1]}: ${err.msg}`).join(', ');
          }
        }
      } catch {
        // Keep default message if parsing fails
      }
    }
    window.dispatchEvent(new CustomEvent('api-error', {
      detail: { key: error.config?.url || 'unknown', message }
    }));
    throw new Error(message);
  }
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
  access_token?: string;
  token_type: 'bearer';
  user: UserProfile;
};

export const api = {
  auth: {
    async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('auth/signin', credentials);
      return data;
    },
    async signup(userData: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('auth/signup', userData);
      return data;
    },
    async forgotPassword(email: string): Promise<void> {
      await apiInstance.post('auth/forgot-password', { email });
    },
    async resetPassword(payload: { email: string; code: string; new_password: string }): Promise<void> {
      await apiInstance.post('auth/reset-password', payload);
    },
    async me(): Promise<UserProfile> {
      const { data } = await apiInstance.get<UserProfile>('auth/me');
      return data;
    },
    async changePassword(payload: { current_password: string; new_password: string }): Promise<void> {
      await apiInstance.post('auth/change-password', payload);
    },
    async signout(): Promise<void> {
      await apiInstance.post('auth/signout');
    },
  },
  support: {
    async listTickets(): Promise<SupportTicket[]> {
      const { data } = await apiInstance.get<SupportTicket[]>('support/tickets');
      return data;
    },
    async createTicket(payload: { subject: string; message: string }): Promise<SupportTicket> {
      const { data } = await apiInstance.post<SupportTicket>('support/ticket', payload);
      return data;
    },
    async listMessages(ticketId: number): Promise<SupportMessage[]> {
      const { data } = await apiInstance.get<SupportMessage[]>(`support/ticket/${ticketId}/messages`);
      return data;
    },
    async sendMessage(ticketId: number, content: string): Promise<SupportMessage> {
      const { data } = await apiInstance.post<SupportMessage>(`support/ticket/${ticketId}/message`, { content });
      return data;
    },
  },
  alerts: {
    async create(payload: AlertCreate): Promise<AlertResponse> {
      const { data } = await apiInstance.post<AlertResponse>('alerts', payload);
      return data;
    },
    async list(): Promise<AlertResponse[]> {
      const { data } = await apiInstance.get<AlertResponse[]>('alerts');
      return data;
    },
    async remove(alertId: number): Promise<void> {
      await apiInstance.delete(`alerts/${alertId}`);
    },
  },
  insights: {
    async analyze(asset: string, language: 'fa' | 'en'): Promise<AnalyzeResponse> {
      const { data } = await apiInstance.post<AnalyzeResponse>('insights/analyze', { asset, language });
      return data;
    },
    async chat(messages: ChatMessage[], language: 'fa' | 'en', session_id?: number | null): Promise<ChatResponse> {
      const { data } = await apiInstance.post<ChatResponse>('insights/chat', { messages, language, session_id });
      return data;
    },
    async listSessions(): Promise<ChatSessionSummary[]> {
      const { data } = await apiInstance.get<ChatSessionSummary[]>('insights/chat/sessions');
      return data;
    },
    async getSession(sessionId: number): Promise<ChatSessionDetail> {
      const { data } = await apiInstance.get<ChatSessionDetail>(`insights/chat/sessions/${sessionId}`);
      return data;
    },
    async renameSession(sessionId: number, title: string): Promise<ChatSessionSummary> {
      const { data } = await apiInstance.patch<ChatSessionSummary>(`insights/chat/sessions/${sessionId}`, { title });
      return data;
    },
    async deleteSession(sessionId: number): Promise<void> {
      await apiInstance.delete(`insights/chat/sessions/${sessionId}`);
    },
  },
  notifications: {
    async list(): Promise<NotificationItem[]> {
      const { data } = await apiInstance.get<NotificationItem[] | { items?: NotificationItem[]; notifications?: NotificationItem[] }>('notifications');
      if (Array.isArray(data)) return data;
      return data.notifications ?? data.items ?? [];
    },
    async markRead(id: number | string): Promise<NotificationItem> {
      const { data } = await apiInstance.patch<NotificationItem>(`notifications/${encodeURIComponent(String(id))}/read`);
      return data;
    },
    async readAll(): Promise<void> {
      await apiInstance.post('notifications/read-all');
    },
    async preferences(): Promise<NotificationPreferences> {
      const { data } = await apiInstance.get<NotificationPreferences>('notifications/preferences');
      return data;
    },
    async setBasic(key: 'push_app' | 'silent_mode' | 'aggressive_alerts', enabled: boolean): Promise<NotificationPreferences> {
      const { data } = await apiInstance.patch<NotificationPreferences>(`notifications/preferences/${key}`, { enabled });
      return data;
    },
    async startOtp(channel: 'sms' | 'email', destination: string): Promise<{ message: string; destination: string; ttl_minutes: number }> {
      const { data } = await apiInstance.post('notifications/otp/start', { channel, destination });
      return data;
    },
    async confirmOtp(channel: 'sms' | 'email', destination: string, code: string): Promise<NotificationPreferences> {
      const { data } = await apiInstance.post<NotificationPreferences>('notifications/otp/confirm', { channel, destination, code });
      return data;
    },
    async setTelegram(telegram_id: string): Promise<NotificationPreferences> {
      const { data } = await apiInstance.post<NotificationPreferences>('notifications/telegram', { telegram_id });
      return data;
    },
    async disable(channel: 'sms' | 'email' | 'telegram'): Promise<NotificationPreferences> {
      const { data } = await apiInstance.delete<NotificationPreferences>(`notifications/${channel}`);
      return data;
    },
    async confirmTelegram(code: string): Promise<NotificationPreferences> {
      const { data } = await apiInstance.post<NotificationPreferences>('notifications/telegram/confirm', { code });
      return data;
    },
    async createTelegramDeepLink(): Promise<TelegramDeepLink> {
      const { data } = await apiInstance.post<TelegramDeepLink>('notifications/telegram/deep-link');
      return data;
    },
  },
  instruments: {
    async list(): Promise<InstrumentSummary[]> {
      const { data } = await apiInstance.get<InstrumentSummary[] | { instruments?: InstrumentSummary[]; items?: InstrumentSummary[] }>('instruments');
      if (Array.isArray(data)) return data;
      return data.instruments ?? data.items ?? [];
    },
    async get(instrumentId: string): Promise<InstrumentSummary> {
      const { data } = await apiInstance.get<InstrumentSummary>(`instruments/${encodeURIComponent(instrumentId)}`);
      return data;
    },
    async sources(instrumentId: string): Promise<InstrumentSourcesResponse> {
      const { data } = await apiInstance.get<InstrumentSourcesResponse | InstrumentSourceQuote[] | { data?: InstrumentSourcesResponse }>(`instruments/${encodeURIComponent(instrumentId)}/sources`);
      if (Array.isArray(data)) return { instrument_id: instrumentId, sources: data };
      const payload = 'data' in data && data.data ? data.data : data as InstrumentSourcesResponse;
      return { ...payload, instrument_id: payload.instrument_id ?? instrumentId, sources: Array.isArray(payload.sources) ? payload.sources : [] };
    },
    async history(instrumentId: string, timeframe: PriceTimeframe = '24h'): Promise<InstrumentHistoryResponse> {
      const { data } = await apiInstance.get<InstrumentHistoryResponse>(`instruments/${encodeURIComponent(instrumentId)}/history`, {
        params: { timeframe },
      });
      return data;
    },
    async sourceHistory(instrumentId: string, timeframe: PriceTimeframe = '24h'): Promise<InstrumentSourceHistoryResponse> {
      const { data } = await apiInstance.get<InstrumentSourceHistoryResponse>(`instruments/${encodeURIComponent(instrumentId)}/sources/history`, {
        params: { timeframe },
      });
      return data;
    },
    async verification(instrumentId: string): Promise<InstrumentVerification> {
      const { data } = await apiInstance.get<InstrumentVerification>(`instruments/${encodeURIComponent(instrumentId)}/verification`);
      return data;
    },
    async health(instrumentId: string): Promise<Record<string, unknown>> {
      const { data } = await apiInstance.get<Record<string, unknown>>(`instruments/${encodeURIComponent(instrumentId)}/health`);
      return data;
    },
  },
};

export type AnalyzeResponse = {
  asset: string;
  analysis: string;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};

export type ChatResponse = {
  session_id: number;
  reply: string;
};

export type ChatSessionSummary = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatSessionDetail = ChatSessionSummary & {
  messages: ChatMessage[];
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
  stale_at?: string | null;
  expires_at?: string | null;
  is_persisted?: boolean;
  verification_status?: string | null;
};

export type InstrumentSourceQuote = {
  id?: number | string;
  provider_id?: string;
  provider_name?: string;
  role?: 'primary' | 'verifier' | 'fallback' | 'derived' | string;
  price: number | null;
  status?: OperationalPriceStatus | 'rejected';
  observed_at?: string | null;
  received_at?: string | null;
  age_seconds?: number | null;
  difference_percent?: number | null;
  is_direct?: boolean;
  is_derived?: boolean;
  is_suspicious?: boolean;
  rejection_reason?: string | null;
  currency?: string;
  weight_unit?: string | null;
  purity?: string | number | null;
};

export type InstrumentSourcesResponse = {
  instrument_id: string;
  status?: OperationalPriceStatus;
  canonical_price?: number | null;
  candidate_price?: number | null;
  candidate_provider?: string | null;
  candidate_observed_at?: string | null;
  difference_percent?: number | null;
  verification_status?: string | null;
  sources: InstrumentSourceQuote[];
};

export type InstrumentSourceHistoryResponse = {
  instrument_id: string;
  timeframe?: string;
  status?: 'complete' | 'partial' | string;
  sources: Array<{ provider_id: string; provider_name?: string; points: Array<{ timestamp: string; value: number }> }>;
};

export type InstrumentHistoryResponse = {
  instrument_id: string;
  timeframe?: string;
  status?: 'complete' | 'partial' | string;
  points: Array<{ timestamp: string; value: number; status?: OperationalPriceStatus }>;
};

export type InstrumentVerification = {
  instrument_id: string;
  status: string;
  candidate_price?: number | null;
  canonical_price?: number | null;
  candidate_provider?: string | null;
  difference_percent?: number | null;
  decision_reason?: string | null;
  updated_at?: string | null;
};

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

export type AlertResponse = {
  id: number;
  asset: string;
  target_price: number | null;
  alert_type: 'price' | 'formula';
  formula: string | null;
  currency_mode: CurrencyMode;
  condition: 'above' | 'below';
  notify_app: boolean;
  notify_email: boolean;
  notify_webhook: boolean;
  webhook_url: string | null;
  enable_dlq: boolean;
  is_active: boolean;
  created_at: string;
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

export type CurrencyMode = 'usd' | 'toman';

export type PriceAsset = {
  asset: string;
  label_fa: string;
  label_en: string;
  price_usd: number | null;
  price_toman: number | null;
  change_percent: number;
  trend: 'up' | 'down';
  history: any[];
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

export type PriceHistoryResponse = {
  asset: string;
  points: PricePoint[];
};

export type PricesResponse = {
  refreshed_at: string;
  source: { usd?: string; toman?: string };
  assets: PriceAsset[];
};

export type PriceTimeframe = '1h' | '24h' | '7d' | '30d' | '1y';

export const queryKeys = {
  prices: ['prices'] as const,
  priceHistory: (asset: string, timeframe: PriceTimeframe) => ['prices', asset, 'history', timeframe] as const,
  alerts: ['alerts'] as const,
  profile: ['profile'] as const,
  analysis: (asset: string, language: 'fa' | 'en') => ['insights', 'analysis', asset, language] as const,
  chatSessions: ['insights', 'chat', 'sessions'] as const,
  chatSession: (sessionId: number) => ['insights', 'chat', 'sessions', sessionId] as const,
};

export const getPrices = async (signal?: AbortSignal): Promise<PricesResponse> => {
  const { data } = await apiInstance.get<PricesResponse>('prices', { signal });
  return data;
};

export const getPriceHistory = async (
  asset: string,
  timeframe: PriceTimeframe = '24h',
  signal?: AbortSignal,
): Promise<PriceHistoryResponse> => {
  const { data } = await apiInstance.get<PriceHistoryResponse>(`prices/${asset}/history`, {
    params: { timeframe },
    signal,
  });
  return data;
};

export const getPricesWebSocketUrl = (): string => {
  const url = new URL(baseURL, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/api\/?$/, '').replace(/\/$/, '')}/api/ws/prices`;
  url.search = '';
  url.hash = '';
  return url.toString();
};

export const formatPrice = (value: number | null | undefined, mode: CurrencyMode, language: 'en' | 'fa'): string => {
  if (value === null || value === undefined) return '--';
  
  const locale = language === 'fa' ? 'fa-IR' : 'en-US';
  
  if (mode === 'usd') {
    // Return raw formatted number without currency symbol. The UI will render the correct symbol.
    return new Intl.NumberFormat(locale, {
      style: 'decimal',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  } else {
    // Return raw formatted number without Toman string. The UI will render the correct symbol.
    return new Intl.NumberFormat(locale, {
      style: 'decimal',
      maximumFractionDigits: 0
    }).format(value);
  }
};
