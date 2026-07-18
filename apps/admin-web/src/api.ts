import type { AdminProfile, JsonRecord, SigninResponse } from "./types";

const configuredBase =
  import.meta.env.VITE_ADMIN_API_URL || import.meta.env.VITE_ADMIN_API_BASE || "/api/admin";
const API_BASE = configuredBase.replace(/\/$/, "");
const CSRF_STORAGE_KEY = "nerkhbaan_admin_csrf";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail && "message" in detail
          ? String((detail as { message: unknown }).message)
          : `Request failed (${status})`;
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function saveCsrf(value: string | null): void {
  if (value) {
    sessionStorage.setItem(CSRF_STORAGE_KEY, value);
  } else {
    sessionStorage.removeItem(CSRF_STORAGE_KEY);
  }
}

async function parseResponse(response: Response): Promise<any> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload ? payload.detail : payload;
    throw new ApiError(response.status, detail);
  }
  return payload;
}

async function refreshCsrf(): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = await parseResponse(response);
  saveCsrf(payload.csrf_token);
  return payload.csrf_token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = sessionStorage.getItem(CSRF_STORAGE_KEY) || (await refreshCsrf());
    headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    credentials: "include",
    headers,
  });
  return parseResponse(response) as Promise<T>;
}

export const adminApi = {
  async signin(identifier: string, password: string): Promise<SigninResponse> {
    const response = await fetch(`${API_BASE}/auth/signin`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ identifier, password }),
    });
    const payload = (await parseResponse(response)) as SigninResponse;
    saveCsrf(payload.csrf_token);
    return payload;
  },
  async me(): Promise<AdminProfile> {
    const payload = await request<{ admin: AdminProfile }>("/auth/me");
    await refreshCsrf();
    return payload.admin;
  },
  async reauthenticate(password: string): Promise<void> {
    await request("/auth/reauthenticate", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await request("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },
  async signout(): Promise<void> {
    try {
      await request("/auth/signout", { method: "POST" });
    } finally {
      saveCsrf(null);
    }
  },
  get<T = JsonRecord>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T = JsonRecord>(path: string, body: unknown = {}): Promise<T> {
    return request<T>(path, { method: "POST", body: JSON.stringify(body) });
  },
  put<T = JsonRecord>(path: string, body: unknown): Promise<T> {
    return request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  },
  patch<T = JsonRecord>(path: string, body: unknown): Promise<T> {
    return request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  },
};
