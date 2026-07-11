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
  headers: {
    'Content-Type': 'application/json',
  },
});

apiInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem('authToken');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiInstance.interceptors.response.use(
  (response) => {
    window.dispatchEvent(new CustomEvent('api-error-clear', {
      detail: { key: response.config.url || 'unknown' }
    }));
    return response;
  },
  async (error) => {
    console.error('API Error:', error.response?.data || error.message);
    
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
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
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
};

export type AlertCreate = {
  asset: string;
  target_price: number;
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
  target_price: number;
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
  status: 'open' | 'answered' | 'closed';
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
  usd_status: 'live' | 'cached' | 'unavailable';
  toman_status: 'live' | 'cached' | 'unavailable';
  stale_minutes: number | null;
  chart_error: boolean;
  chart_error_message: { fa: string; en: string };
};

export type PricePoint = {
  timestamp: string;
  value_usd: number | null;
  value_toman: number | null;
};

export type PriceHistoryResponse = {
  asset: string;
  points: PricePoint[];
};

export const getPrices = async () => {
  // Use relative path to prevent Axios from stripping the /api base path
  const { data } = await apiInstance.get('prices');
  return data;
};

export const getPriceHistory = async (asset: string): Promise<PriceHistoryResponse> => {
  const { data } = await apiInstance.get<PriceHistoryResponse>(`prices/${asset}/history`);
  return data;
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
