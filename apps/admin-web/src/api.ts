import type { AdminProfile, JsonRecord, SigninResponse } from "./types";

const configuredBase =
  import.meta.env.VITE_ADMIN_API_URL ||
  import.meta.env.VITE_ADMIN_API_BASE ||
  "/api/admin";
const API_BASE = configuredBase.replace(/\/$/, "");
const CSRF_STORAGE_KEY = "nerkhbaan_admin_csrf";
const REQUEST_TIMEOUT_MS = 15_000;

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

function sessionExpired(): void {
  saveCsrf(null);
  window.dispatchEvent(new Event("admin-session-expired"));
}

async function bounded<T>(
  signal: AbortSignal | null | undefined,
  write: boolean,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel = () => {};
  const stopped = new Promise<never>((_resolve, reject) => {
    cancel = () => {
      reject(new DOMException("Request cancelled", "AbortError"));
      controller.abort();
    };
    if (signal?.aborted) return cancel();
    signal?.addEventListener("abort", cancel, { once: true });
    timer = setTimeout(() => {
      reject(new ApiError(408, write
        ? "Request timed out. The action may have completed. Check current data before trying again."
        : "Request timed out. Try loading the data again."));
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
  });
  try {
    if (controller.signal.aborted) return await stopped;
    return await Promise.race([operation(controller.signal), stopped]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

async function parseResponse(response: Response): Promise<any> {
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload && "detail" in payload
        ? payload.detail
        : payload;
    throw new ApiError(response.status, detail);
  }
  return payload;
}

async function refreshCsrf(signal?: AbortSignal): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: "include",
    headers: { Accept: "application/json" },
    signal,
  });
  signal?.throwIfAborted();
  if (response.status === 401) sessionExpired();
  const payload = await parseResponse(response);
  signal?.throwIfAborted();
  saveCsrf(payload.csrf_token);
  return payload.csrf_token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const write = !["GET", "HEAD", "OPTIONS"].includes(method);
  return bounded(init.signal, write, async (signal) => {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      const csrf =
        sessionStorage.getItem(CSRF_STORAGE_KEY) || (await refreshCsrf(signal));
      headers.set("X-CSRF-Token", csrf);
    }
    signal.throwIfAborted();
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      method,
      credentials: "include",
      headers,
      signal,
    });
    signal.throwIfAborted();
    if (response.status === 401) {
      const payload = await response
        .clone()
        .json()
        .catch(() => null);
      signal.throwIfAborted();
      const message = typeof payload?.detail === "string" ? payload.detail : "";
      const codeFailure =
        (path.startsWith("/auth/reauthenticate") ||
          path.startsWith("/auth/mfa")) &&
        (message.startsWith("MFA code") || message === "Password is incorrect");
      if (!codeFailure) sessionExpired();
    }
    return parseResponse(response) as Promise<T>;
  });
}

export const adminApi = {
  async signin(
    identifier: string,
    password: string,
    mfaCode = "",
  ): Promise<SigninResponse> {
    return bounded(undefined, true, async (signal) => {
      const response = await fetch(`${API_BASE}/auth/signin`, {
        method: "POST",
        credentials: "include",
        signal,
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          identifier,
          password,
          ...(mfaCode ? { mfa_code: mfaCode } : {}),
        }),
      });
      const payload = (await parseResponse(response)) as SigninResponse;
      signal.throwIfAborted();
      saveCsrf(payload.csrf_token);
      return payload;
    });
  },
  async me(): Promise<AdminProfile> {
    const payload = await request<{ admin: AdminProfile }>("/auth/me");
    await bounded(undefined, false, (signal) => refreshCsrf(signal));
    return payload.admin;
  },
  async reauthenticate(password: string, mfaCode = ""): Promise<void> {
    await request("/auth/reauthenticate", {
      method: "POST",
      body: JSON.stringify({
        password,
        ...(mfaCode ? { mfa_code: mfaCode } : {}),
      }),
    });
  },
  async changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    await request("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  },
  async signout(): Promise<void> {
    try {
      await request("/auth/signout", { method: "POST" });
    } finally {
      saveCsrf(null);
    }
  },
  get<T = JsonRecord>(path: string, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { signal });
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
  delete<T = JsonRecord>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "DELETE",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  },
  async download(path: string, signal?: AbortSignal): Promise<Blob> {
    return bounded(signal, false, async (requestSignal) => {
      const response = await fetch(`${API_BASE}${path}`, {
        credentials: "include",
        signal: requestSignal,
      });
      requestSignal.throwIfAborted();
      if (response.status === 401) sessionExpired();
      if (!response.ok) {
        await parseResponse(response);
      }
      return response.blob();
    });
  },
};
