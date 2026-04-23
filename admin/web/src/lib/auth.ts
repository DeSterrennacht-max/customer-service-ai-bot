import { TokenResponse } from "@/types/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
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
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
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

export async function refreshTokens(refreshToken = getRefreshToken()): Promise<TokenResponse> {
  if (!refreshToken) {
    clearTokens();
    throw new AuthError("Session expired");
  }

  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if (response.status === 401) {
    clearTokens();
    throw new AuthError("Session expired");
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const tokens = (await response.json()) as TokenResponse;
  storeTokens(tokens);
  return tokens;
}

export async function ensureAccessToken(forceRefresh = false): Promise<string> {
  if (!isBrowser()) {
    throw new AuthError("Authentication required");
  }

  if (!forceRefresh) {
    const accessToken = getAccessToken();
    if (accessToken) {
      return accessToken;
    }
  }

  const tokens = await refreshTokens();
  return tokens.access_token;
}
