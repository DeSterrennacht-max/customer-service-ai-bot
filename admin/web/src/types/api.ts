export type ConversationStatus = "open" | "handoff" | "closed";
export type RiskLevel = "low" | "medium" | "high";

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type UserRole = "super_admin" | "admin" | "agent";

export interface CurrentUser {
  id: string;
  login_username: string;
  email?: string | null;
  role: UserRole;
  tenant_id?: string | null;
  tenant_name?: string | null;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export interface TenantSummary {
  id: string;
  name: string;
  admin_login_username?: string | null;
  status: string;
  valid_from?: string | null;
  valid_until?: string | null;
  created_at: string;
}

export interface TenantCreatePayload {
  name: string;
  login_username: string;
  status: string;
  valid_from?: string | null;
  valid_until?: string | null;
}

export interface TenantUpdatePayload {
  name: string;
  login_username?: string;
  status?: string;
  valid_from?: string | null;
  valid_until?: string | null;
}

export interface TenantCreateResponse extends TenantSummary {
  temporary_password: string;
}

export interface TenantAdminPasswordResetResponse {
  tenant_id: string;
  admin_login_username: string;
  temporary_password: string;
}

export interface Conversation {
  id: string;
  tenant_id: string;
  bot_profile_id: string;
  telegram_user_id: string;
  telegram_chat_id: string;
  telegram_business_connection_id?: string | null;
  customer_display_name?: string | null;
  status: ConversationStatus;
  last_message_at?: string | null;
  last_customer_message_at?: string | null;
  assigned_agent_user_id?: string | null;
  handoff_ticket_id?: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  source: "customer" | "bot" | "agent" | "system";
  channel: "telegram_dm" | "telegram_group";
  content_text: string;
  intent?: string | null;
  risk_level: "low" | "medium" | "high";
  delivery_status: string;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface HandoffActionResponse {
  conversation_id: string;
  handoff_ticket_id?: string | null;
  status: ConversationStatus;
}

export interface FAQEntry {
  id: string;
  bot_profile_id: string;
  tenant_id: string;
  question_patterns_json: string[];
  canonical_answer: string;
  image_assets_json: ImageAsset[];
  answer_style_notes?: string | null;
  category?: string | null;
  product_scope?: string | null;
  risk_level: RiskLevel;
  priority: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface FAQCreatePayload {
  bot_profile_id: string;
  tenant_id?: string | null;
  question_patterns_json: string[];
  canonical_answer: string;
  image_assets_json: ImageAsset[];
  answer_style_notes?: string | null;
  category?: string | null;
  product_scope?: string | null;
  risk_level: RiskLevel;
  priority: number;
  status: string;
}

export interface FAQUpdatePayload {
  question_patterns_json?: string[];
  canonical_answer?: string;
  image_assets_json?: ImageAsset[];
  answer_style_notes?: string | null;
  category?: string | null;
  product_scope?: string | null;
  risk_level?: RiskLevel;
  priority?: number;
  status?: string;
}

export interface KnowledgePage {
  id: string;
  bot_profile_id: string;
  tenant_id: string;
  title: string;
  body_markdown: string;
  image_assets_json: ImageAsset[];
  tags_json: string[];
  product_scope?: string | null;
  risk_level: RiskLevel;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgePageCreatePayload {
  bot_profile_id: string;
  tenant_id?: string | null;
  title: string;
  body_markdown: string;
  image_assets_json: ImageAsset[];
  tags_json: string[];
  product_scope?: string | null;
  risk_level: RiskLevel;
  status: string;
}

export interface KnowledgePageUpdatePayload {
  title?: string;
  body_markdown?: string;
  image_assets_json?: ImageAsset[];
  tags_json?: string[];
  product_scope?: string | null;
  risk_level?: RiskLevel;
  status?: string;
}

export interface ImageAsset {
  url: string;
  object_key: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface StyleProfile {
  id: string;
  bot_profile_id: string;
  tenant_id: string;
  tone: string;
  persona_notes?: string | null;
  banned_phrases_json?: string[] | null;
  delay_min_ms: number;
  delay_max_ms: number;
  typing_enabled: boolean;
  clarify_max_turns: number;
  created_at: string;
  updated_at: string;
}

export interface StyleProfileUpdatePayload {
  bot_profile_id?: string;
  tone?: string;
  persona_notes?: string | null;
  banned_phrases_json?: string[] | null;
  delay_min_ms?: number;
  delay_max_ms?: number;
  typing_enabled?: boolean;
  clarify_max_turns?: number;
}

export interface BotProfile {
  id: string;
  tenant_id: string;
  tenant_name?: string | null;
  name: string;
  telegram_bot_token: string;
  telegram_bot_username?: string | null;
  support_group_chat_id?: string | null;
  welcome_message: string;
  unanswered_fallback_message: string;
  language: string;
  industry?: string | null;
  faq_hint_keywords_json: string[];
  high_risk_keywords_json: string[];
  sensitive_keywords_json: string[];
  is_active: boolean;
  business_connection_status: "not_connected" | "connected_no_reply" | "ready";
  business_connection_id?: string | null;
  business_connection_updated_at?: string | null;
  created_at: string;
}

export interface BotProfileCreatePayload {
  tenant_id?: string | null;
  name: string;
  telegram_bot_token: string;
  telegram_bot_username?: string | null;
  support_group_chat_id?: string | null;
  welcome_message: string;
  unanswered_fallback_message: string;
  telegram_bot_description?: string | null;
  language: string;
  industry?: string | null;
  high_risk_keywords_json: string[];
  sensitive_keywords_json: string[];
  is_active: boolean;
}

export interface BotProfileUpdatePayload {
  tenant_id?: string | null;
  name?: string;
  telegram_bot_token?: string;
  telegram_bot_username?: string | null;
  support_group_chat_id?: string | null;
  welcome_message?: string;
  unanswered_fallback_message?: string;
  telegram_bot_description?: string | null;
  language?: string;
  industry?: string | null;
  high_risk_keywords_json?: string[];
  sensitive_keywords_json?: string[];
  is_active?: boolean;
}

export interface TelegramBotDescriptionResponse {
  description: string;
}
