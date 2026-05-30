export type CurrencyMode = 'usd' | 'toman';

export type AuthResponse = {
  access_token: string;
  token_type: 'bearer';
  user: {
    id: number;
    full_name: string;
    email: string;
    created_at: string;
  };
};

export type PriceAsset = {
  asset: 'gold' | 'silver' | 'usdt' | 'btc';
  label_fa: string;
  label_en: string;
  price_usd: number | null;
  price_toman: number | null;
  change_percent: number;
  trend: 'up' | 'down';
  source_usd: string;
  source_toman: string;
  usd_status: 'live' | 'cached' | 'unavailable';
  toman_status: 'live' | 'cached' | 'unavailable';
  stale_minutes: number | null;
  chart_error: boolean;
  chart_error_message: {
    fa: string;
    en: string;
  };
  history: Array<{
    timestamp: string;
    value_usd: number | null;
    value_toman: number | null;
  }>;
};

export type PricesResponse = {
  refreshed_at: string;
  source: {
    usd: string;
    toman: string;
  };
  assets: PriceAsset[];
};

// Use the Vite environment variable, fallback to localhost for development
const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

interface RequestOptions extends RequestInit {
  timeout?: number;
}

/**
 * Core API request handler.
 * Implements AbortController for timeouts, automatic JWT token injection,
 * and global 401 Unauthorized handling.
 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  // Set default timeout to 8 seconds to prevent indefinite UI hangs on bad connections
  const { timeout = 8000, headers, ...rest } = options;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // Retrieve JWT auth token from local storage
  const token = localStorage.getItem('authToken');

  const defaultHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };

  // Inject token globally if it exists
  if (token) {
    defaultHeaders['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        ...defaultHeaders,
        ...headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      // Global interceptor for expired or invalid tokens
      if (response.status === 401) {
        localStorage.removeItem('authToken');
        // Dispatch an event so your React router can catch it and redirect to /login
        window.dispatchEvent(new Event('auth-expired'));
      }

      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        
        // Handle FastAPI string errors and array-based Pydantic validation errors
        if (body?.detail) {
          if (typeof body.detail === 'string') {
            message = body.detail;
          } else if (Array.isArray(body.detail)) {
            // Extract the exact FastAPI missing fields
            message = body.detail.map((err: any) => 
              `${err.loc[err.loc.length - 1]}: ${err.msg}`
            ).join(', ');
          }
        }
      } catch {
        // Ignore JSON parsing errors for error bodies, fallback to HTTP status
      }

      throw new Error(message);
    }

    // Parse the response text first to handle cases where the server returns an empty body safely
    const text = await response.text();
    return text ? JSON.parse(text) : ({} as T);

  } catch (error: any) {
    clearTimeout(timeoutId);

    // Catch the specific abort event and return a user-friendly error
    if (error.name === 'AbortError') {
      throw new Error('Request timed out. Please check your network connection.');
    }

    throw error;
  }
}

// --- API Endpoints ---

export function signup(payload: {
  full_name: string;
  email: string;
  password: string;
}): Promise<AuthResponse> {
  return request<AuthResponse>('/api/auth/signup', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function signin(payload: { email: string; password: string }): Promise<AuthResponse> {
  return request<AuthResponse>('/api/auth/signin', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function getPrices(): Promise<PricesResponse> {
  return request<PricesResponse>('/api/prices');
}

// --- Utilities ---

export function formatPrice(
  value: number | null | undefined,
  currency: CurrencyMode,
  language: 'fa' | 'en'
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '--';
  }

  const locale = language === 'fa' ? 'fa-IR' : 'en-US';
  const roundedValue = value;

  if (currency === 'usd') {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 2
    }).format(roundedValue);
  }

  const formatted = new Intl.NumberFormat(locale, {
    maximumFractionDigits: 0
  }).format(roundedValue);

  return language === 'fa' ? `${formatted} تومان` : `${formatted} Toman`;
}