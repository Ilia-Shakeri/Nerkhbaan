import axios from 'axios';

// Ensure the base URL correctly points to the API gateway and appends /api to prevent 404 and CORS fetch errors
const envApiUrl = import.meta.env.VITE_API_URL;
const baseURL = envApiUrl 
  ? (envApiUrl.endsWith('/api') ? envApiUrl : `${envApiUrl}/api`) 
  : 'http://127.0.0.1:8000/api';

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

export const api = {
  auth: {
    async signin(credentials: { username_or_email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signin', credentials);
      return data;
    },
    async signup(userData: { username: string; full_name: string; email: string; password: string }): Promise<AuthResponse> {
      const { data } = await apiInstance.post<AuthResponse>('/auth/signup', userData);
      return data;
    },
    async forgotPassword(email: string): Promise<void> {
        await apiInstance.post('/auth/forgot-password', { email });
    }
  }
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

export const getPrices = async () => {
  const { data } = await apiInstance.get('/prices');
  return data;
};

export const formatPrice = (value: number | null | undefined, mode: CurrencyMode, language: 'en' | 'fa'): string => {
  if (value === null || value === undefined) return '--';
  
  const locale = language === 'fa' ? 'fa-IR' : 'en-US';
  
  if (mode === 'usd') {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  } else {
    // Format Toman without fractional digits
    const formatted = new Intl.NumberFormat(locale, {
      maximumFractionDigits: 0
    }).format(value);
    return language === 'fa' ? formatted + ' تومان' : 'Toman ' + formatted;
  }
};