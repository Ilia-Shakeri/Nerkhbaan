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

const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;

    try {
      const body = await response.json();
      if (body?.detail && typeof body.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // Ignore body parsing errors.
    }

    throw new Error(message);
  }

  return (await response.json()) as T;
}

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
