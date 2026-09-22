import { TokenResponse } from "@/types/api";
import { getApiBaseUrl } from "@/lib/runtime-config";
const ACCESS_TOKEN_KEY = "csb_access_token";
const REFRESH_TOKEN_KEY = "csb_refresh_token";

export class AuthError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "AuthError";
  }
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string };
    if (typeof data.detail === "string") {
      return data.detail;
    }
  } catch {
    return response.statusText || "Request failed";
  }

  return response.statusText || "Request failed";
}

export function getAccessToken(): string | null {
  if (!isBrowser()) {
    return null;
  }
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (!isBrowser()) {
    return null;
  }
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function storeTokens(tokens: TokenResponse): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken() || getRefreshToken());
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const response = await fetch(`${getApiBaseUrl()}/auth/login`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ username, password })
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const tokens = (await response.json()) as TokenResponse;
  storeTokens(tokens);
  return tokens;
}

async function performRefresh(refreshToken: string | null): Promise<TokenResponse> {
  if (!refreshToken) {
    clearTokens();
    throw new AuthError("Session expired");
  }

  const response = await fetch(`${getApiBaseUrl()}/auth/refresh`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if (response.status === 401) {
    if (getRefreshToken() === refreshToken) clearTokens();
    throw new AuthError("Session expired");
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const tokens = (await response.json()) as TokenResponse;
  if (getRefreshToken() !== refreshToken) throw new AuthError("Session changed");
  storeTokens(tokens);
  return tokens;
}

let refreshInFlight: Promise<TokenResponse> | null = null;

export async function refreshTokens(refreshToken = getRefreshToken()): Promise<TokenResponse> {
  if (refreshInFlight) return refreshInFlight;
  const refresh = async () => {
    const current = getRefreshToken();
    const access = getAccessToken();
    if (current && current !== refreshToken && access) {
      return { access_token: access, refresh_token: current, token_type: "bearer" };
    }
    return performRefresh(current);
  };
  // Serialize token rotation across pages and browser tabs.
  const pending = (async () => {
    if (typeof navigator !== "undefined" && navigator.locks) {
      return await navigator.locks.request("csb-auth-refresh", refresh);
    }
    return await refresh();
  })().finally(() => { refreshInFlight = null; });
  refreshInFlight = pending;
  return pending;
}

export async function logout(): Promise<void> {
  const revoke = async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      const response = await fetch(`${getApiBaseUrl()}/auth/logout`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }), signal: AbortSignal.timeout(10000)
      });
      if (!response.ok && response.status !== 401) throw new Error(await readErrorMessage(response));
    }
    clearTokens();
  };
  if (typeof navigator !== "undefined" && navigator.locks) {
    await navigator.locks.request("csb-auth-refresh", revoke);
  } else {
    if (refreshInFlight) await refreshInFlight.catch(() => undefined);
    await revoke();
  }
}

export async function ensureAccessToken(forceRefresh = false, rejectedToken?: string): Promise<string> {
  if (!isBrowser()) {
    throw new AuthError("Authentication required");
  }

  if (!forceRefresh) {
    const accessToken = getAccessToken();
    if (accessToken) {
      return accessToken;
    }
  }

  if (forceRefresh && rejectedToken && getAccessToken() && getAccessToken() !== rejectedToken) {
    return getAccessToken()!;
  }
  const tokens = await refreshTokens();
  return tokens.access_token;
}
