import { AuthError, clearTokens, ensureAccessToken } from "@/lib/auth";
import { getApiBaseUrl } from "@/lib/runtime-config";
import {
  ChangePasswordPayload,
  CurrentUser,
  Conversation,
  ConversationDetail,
  FAQCreatePayload,
  FAQEntry,
  FAQUpdatePayload,
  HandoffActionResponse,
  KnowledgePageCreatePayload,
  KnowledgePage,
  KnowledgePageUpdatePayload,
  BotProfile,
  BotProfileCreatePayload,
  BotProfileUpdatePayload,
  StyleProfile,
  StyleProfileUpdatePayload,
  TenantAdminPasswordResetResponse,
  TenantCreateResponse,
  TenantSummary,
  TenantCreatePayload,
  TenantUpdatePayload
} from "@/types/api";

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

async function requestJSON<T>(path: string, init: RequestInit = {}, retryOnUnauthorized = true): Promise<T> {
  let accessToken: string;
  try {
    accessToken = await ensureAccessToken();
  } catch (error) {
    if (error instanceof AuthError) {
      throw error;
    }
    throw new AuthError();
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
      Authorization: `Bearer ${accessToken}`
    },
    cache: "no-store"
  });

  if (response.status === 401 && retryOnUnauthorized) {
    try {
      await ensureAccessToken(true);
    } catch (error) {
      clearTokens();
      if (error instanceof AuthError) {
        throw error;
      }
      throw new AuthError();
    }
    return requestJSON<T>(path, init, false);
  }

  if (response.status === 401) {
    clearTokens();
    throw new AuthError("Session expired");
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

function withQuery(path: string, params: Record<string, string | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) {
      search.set(key, value);
    }
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export const api = {
  me: () => requestJSON<CurrentUser>("/auth/me"),
  changePassword: (payload: ChangePasswordPayload) =>
    requestJSON<void>("/auth/change-password", { method: "POST", body: JSON.stringify(payload) }),
  tenants: () => requestJSON<TenantSummary[]>("/admin/tenants"),
  createTenant: (payload: TenantCreatePayload) =>
    requestJSON<TenantCreateResponse>("/admin/tenants", { method: "POST", body: JSON.stringify(payload) }),
  updateTenant: (id: string, payload: TenantUpdatePayload) =>
    requestJSON<TenantSummary>(`/admin/tenants/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  resetTenantAdminPassword: (id: string) =>
    requestJSON<TenantAdminPasswordResetResponse>(`/admin/tenants/${id}/reset-admin-password`, { method: "POST" }),
  conversations: () => requestJSON<Conversation[]>("/admin/conversations"),
  conversation: (id: string) => requestJSON<ConversationDetail>(`/admin/conversations/${id}`),
  botProfiles: (tenantId?: string | null) => requestJSON<BotProfile[]>(withQuery("/admin/bot-profiles", { tenant_id: tenantId })),
  createBotProfile: (payload: BotProfileCreatePayload) =>
    requestJSON<BotProfile>("/admin/bot-profiles", { method: "POST", body: JSON.stringify(payload) }),
  updateBotProfile: (id: string, payload: BotProfileUpdatePayload) =>
    requestJSON<BotProfile>(`/admin/bot-profiles/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteBotProfile: (id: string) => requestJSON<void>(`/admin/bot-profiles/${id}`, { method: "DELETE" }),
  faqs: (botProfileId?: string | null) => requestJSON<FAQEntry[]>(withQuery("/admin/faqs", { bot_profile_id: botProfileId })),
  createFaq: (payload: FAQCreatePayload) =>
    requestJSON<FAQEntry>("/admin/faqs", { method: "POST", body: JSON.stringify(payload) }),
  updateFaq: (id: string, payload: FAQUpdatePayload) =>
    requestJSON<FAQEntry>(`/admin/faqs/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteFaq: (id: string) => requestJSON<void>(`/admin/faqs/${id}`, { method: "DELETE" }),
  knowledgePages: (botProfileId?: string | null) =>
    requestJSON<KnowledgePage[]>(withQuery("/admin/knowledge-pages", { bot_profile_id: botProfileId })),
  createKnowledgePage: (payload: KnowledgePageCreatePayload) =>
    requestJSON<KnowledgePage>("/admin/knowledge-pages", { method: "POST", body: JSON.stringify(payload) }),
  updateKnowledgePage: (id: string, payload: KnowledgePageUpdatePayload) =>
    requestJSON<KnowledgePage>(`/admin/knowledge-pages/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteKnowledgePage: (id: string) => requestJSON<void>(`/admin/knowledge-pages/${id}`, { method: "DELETE" }),
  styleProfile: (botProfileId?: string | null) => requestJSON<StyleProfile>(withQuery("/admin/style-profile", { bot_profile_id: botProfileId })),
  updateStyleProfile: (payload: StyleProfileUpdatePayload) =>
    requestJSON<StyleProfile>(withQuery("/admin/style-profile", { bot_profile_id: payload.bot_profile_id ?? undefined }), {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  takeoverConversation: (id: string) =>
    requestJSON<HandoffActionResponse>(`/admin/conversations/${id}/takeover`, { method: "POST" }),
  releaseConversation: (id: string) =>
    requestJSON<HandoffActionResponse>(`/admin/conversations/${id}/release`, { method: "POST" })
};
