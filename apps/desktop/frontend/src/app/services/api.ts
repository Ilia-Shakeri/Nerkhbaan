import axios from 'axios';

const baseURL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';

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
  (response) => response,
  async (error) => {
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
        // ignore
      }
    }
    throw new Error(message);
  }
);

export type AuthResponse = {
  access_token: string;
  token_type: 'bearer';
  user: {
    id: number;
    username: string;
    full_name: string;
    email: string;
    created_at: string;
  };
};

export type PricePoint = {
  timestamp: string;
  value_usd: number | null;
  value_toman: number | null;
};

export type PriceAsset = {
  asset: 'gold' | 'silver' | 'usdt' | 'btc';
  label_fa: string;
  label_en: string;
  price_usd: number | null;
  price_toman: number | null;
  change_percent: number;
  trend: 'up' | 'down';
  history: PricePoint[];
  source_usd: string;
  source_toman: string;
  usd_status: 'live' | 'cached' | 'unavailable';
  toman_status: 'live' | 'cached' | 'unavailable';
  stale_minutes: number | null;
  chart_error: boolean;
  chart_error_message: { [key: string]: string };
};

export type PricesResponse = {
  refreshed_at: string;
  source: { [key: string]: string };
  assets: PriceAsset[];
};

export type ProviderHealthStatus = {
  provider_id: string;
  provider_name: string;
  status: string;
  last_success_time: string | null;
  has_api_key: boolean;
};

export type PriceChainHealth = {
  status: string;
  source: string;
  updated_at: string | null;
  error: string | null;
  providers: ProviderHealthStatus[];
};

export type PriceAssetHealth = {
  iran: PriceChainHealth;
  international: PriceChainHealth;
};

export type PricingStartupChecks = {
  checked_at: string;
  required_env_keys: string[];
  missing_env_keys: string[];
  optional_env_keys: string[];
  missing_optional_env_keys: string[];
  strict_mode: boolean;
  ok: boolean;
};

export type PricesHealthResponse = {
  checked_at: string;
  last_refresh_at: string | null;
  startup: PricingStartupChecks;
  chains: { [key: string]: PriceAssetHealth };
};

export const api = {
  auth: {
    async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signin', credentials);
      return data;
    },
    async signup(userData: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signup', userData);
      return data;
    }
  },
  prices: {
    async getPrices(): Promise<PricesResponse> {
      const { data } = await apiInstance.get<PricesResponse>('/prices');
      return data;
    },
    async getHealth(): Promise<PricesHealthResponse> {
      const { data } = await apiInstance.get<PricesHealthResponse>('/prices/health');
      return data;
    }
  }
};