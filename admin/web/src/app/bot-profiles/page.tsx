"use client";

import { FormEvent, useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { getApiBaseUrl } from "@/lib/runtime-config";
import { BotProfile, BotProfileCreatePayload, BotProfileUpdatePayload, CurrentUser, TenantSummary } from "@/types/api";

interface BotProfileFormState {
  tenant_id: string;
  name: string;
  telegram_bot_token: string;
  telegram_bot_username: string;
  support_group_chat_id: string;
  welcome_message: string;
  unanswered_fallback_message: string;
  email_auto_reply_enabled: boolean;
  email_auto_reply_message: string;
  telegram_bot_description: string;
  language: string;
  industry: string;
  high_risk_keywords_text: string;
  sensitive_keywords_text: string;
  is_active: boolean;
}

const DEFAULT_WELCOME_MESSAGE =
  "你好，我是客服助手。你可以直接告诉我你想了解价格、套餐、功能，或者把你遇到的问题发给我，我会先帮你处理；如果你需要人工、投诉或退款，也可以直接说。";
const DEFAULT_UNANSWERED_FALLBACK_MESSAGE = "稍等，这会儿有点忙，我马上处理";
const DEFAULT_EMAIL_AUTO_REPLY_MESSAGE = "已收到你的邮箱，我们会根据你提供的信息继续处理。";

const DEFAULT_FORM: BotProfileFormState = {
  tenant_id: "",
  name: "",
  telegram_bot_token: "",
  telegram_bot_username: "",
  support_group_chat_id: "",
  welcome_message: DEFAULT_WELCOME_MESSAGE,
  unanswered_fallback_message: DEFAULT_UNANSWERED_FALLBACK_MESSAGE,
  email_auto_reply_enabled: true,
  email_auto_reply_message: DEFAULT_EMAIL_AUTO_REPLY_MESSAGE,
  telegram_bot_description: "",
  language: "zh",
  industry: "",
  high_risk_keywords_text: "人工\n投诉\n退款\n退费\n律师\n举报",
  sensitive_keywords_text: "骂\n骗\n垃圾\n诈骗",
  is_active: true
};

const BOT_GUIDE = [
  {
    title: "机器人 API Token",
    description: "填写 BotFather 给你的 bot token。系统会用它收发 Telegram 消息。"
  },
  {
    title: "对应客服群",
    description: "填写这个 Bot 对应的人工客服群 ID。触发转人工时，会优先把消息转到这里。"
  },
  {
    title: "欢迎语",
    description: "用户发送 /start 时，会直接回复这里的欢迎语。每个 Bot 都可以单独设置，不再共用一条固定文案。"
  },
  {
    title: "兜底回复",
    description: "只有普通 Bot 私聊未命中 FAQ 和知识库时，才会发送这条回复并转人工。Business 私聊未命中不会发送。"
  },
  {
    title: "邮箱自动回复",
    description: "用户消息里包含邮箱地址时，会直接回复这里配置的内容，适合开户、注册、资料收集等场景。"
  },
  {
    title: "Bot Description",
    description: "填写后会同步到 Telegram 的 bot description；系统不保存这段内容，留空不会修改 Telegram 当前描述。"
  },
  {
    title: "分流规则",
    description: "机器人现在只保留人工相关词。命中高风险词或敏感词会直接转人工；其他问题统一先查 FAQ，再查知识页，最后才澄清。"
  },
  {
    title: "高风险 / 敏感词",
    description: "高风险词适合退款、投诉、律师介入；敏感词适合辱骂、诈骗等场景。支持逗号或换行分隔。"
  },
  {
    title: "Business Bot 接入",
    description: "BotFather 开启 Business Mode 后，让 Telegram Business 账号连接这个 Bot，并授权读取消息和回复权限。"
  }
] as const;

function listToText(values: string[] | null | undefined): string {
  return values?.join("\n") ?? "";
}

function splitText(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function botToForm(bot: BotProfile): BotProfileFormState {
  return {
    tenant_id: bot.tenant_id,
    name: bot.name,
    telegram_bot_token: bot.telegram_bot_token,
    telegram_bot_username: bot.telegram_bot_username ?? "",
    support_group_chat_id: bot.support_group_chat_id ?? "",
    welcome_message: bot.welcome_message,
    unanswered_fallback_message: bot.unanswered_fallback_message || DEFAULT_UNANSWERED_FALLBACK_MESSAGE,
    email_auto_reply_enabled: bot.email_auto_reply_enabled,
    email_auto_reply_message: bot.email_auto_reply_message || DEFAULT_EMAIL_AUTO_REPLY_MESSAGE,
    telegram_bot_description: "",
    language: bot.language,
    industry: bot.industry ?? "",
    high_risk_keywords_text: listToText(bot.high_risk_keywords_json),
    sensitive_keywords_text: listToText(bot.sensitive_keywords_json),
    is_active: bot.is_active
  };
}

function normalizeUsername(value: string): string {
  return value.trim().replace(/^@+/, "");
}

function businessConnectionLabel(bot: BotProfile): string {
  if (bot.business_connection_status === "ready") {
    return "可自动回复";
  }
  if (bot.business_connection_status === "connected_no_reply") {
    return "已连接，缺少回复权限";
  }
  return "未连接";
}

export default function BotProfilesPage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [bots, setBots] = useState<BotProfile[]>([]);
  const [tenantFilter, setTenantFilter] = useState<string>("all");
  const [form, setForm] = useState<BotProfileFormState>(DEFAULT_FORM);
  const [editingBotId, setEditingBotId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isDescriptionLoading, setIsDescriptionLoading] = useState(false);
  const [isPending, startTransition] = useTransition();

  const isSuperAdmin = me?.role === "super_admin";
  const exampleWebhookBase = useMemo(() => {
    return `${getApiBaseUrl()}/telegram/webhook`;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadContext() {
      try {
        const [currentUser, tenantData] = await Promise.all([api.me(), api.tenants()]);
        if (cancelled) {
          return;
        }
        const currentUserIsSuperAdmin = currentUser.role === "super_admin";
        setMe(currentUser);
        setTenants(tenantData);
        if (!currentUserIsSuperAdmin && tenantData[0]) {
          setTenantFilter(tenantData[0].id);
          setForm((current) => ({ ...current, tenant_id: tenantData[0].id }));
        }
        if (currentUserIsSuperAdmin && tenantData[0]) {
          setForm((current) => ({ ...current, tenant_id: tenantData[0].id }));
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "机器人配置加载失败");
      }
    }

    void loadContext();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!me) {
      return;
    }

    let cancelled = false;

    async function loadBots() {
      try {
        const data = await api.botProfiles(isSuperAdmin && tenantFilter !== "all" ? tenantFilter : null);
        if (cancelled) {
          return;
        }
        setBots(data);
        setError(null);
        if (!editingBotId && !form.tenant_id) {
          const nextTenantId = isSuperAdmin ? (tenantFilter !== "all" ? tenantFilter : data[0]?.tenant_id ?? "") : me?.tenant_id ?? "";
          setForm((current) => ({ ...current, tenant_id: nextTenantId }));
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "机器人配置加载失败");
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadBots();
    return () => {
      cancelled = true;
    };
  }, [router, me, isSuperAdmin, tenantFilter, editingBotId, form.tenant_id]);

  function updateForm<K extends keyof BotProfileFormState>(key: K, value: BotProfileFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function resetForm() {
    setEditingBotId(null);
    setForm({
      ...DEFAULT_FORM,
      tenant_id: isSuperAdmin ? (tenantFilter !== "all" ? tenantFilter : tenants[0]?.id ?? "") : me?.tenant_id ?? ""
    });
    setSubmitError(null);
    setSubmitMessage(null);
  }

  function startEdit(bot: BotProfile) {
    setEditingBotId(bot.id);
    setForm(botToForm(bot));
    setSubmitError(null);
    setSubmitMessage(null);
  }

  async function loadTelegramDescription() {
    if (!editingBotId) {
      setSubmitError("请先编辑已保存的机器人配置，再读取当前 Bot Description。");
      return;
    }
    setSubmitError(null);
    setSubmitMessage(null);
    setIsDescriptionLoading(true);
    try {
      const data = await api.botProfileTelegramDescription(editingBotId);
      updateForm("telegram_bot_description", data.description);
      setSubmitMessage(data.description ? "已读取当前 Telegram Bot Description。" : "当前 Telegram Bot Description 为空。");
    } catch (loadFailure) {
      if (loadFailure instanceof AuthError) {
        router.replace("/login");
        return;
      }
      setSubmitError(loadFailure instanceof Error ? loadFailure.message : "读取 Telegram Bot Description 失败");
    } finally {
      setIsDescriptionLoading(false);
    }
  }

  async function reloadBots() {
    const nextBots = await api.botProfiles(isSuperAdmin && tenantFilter !== "all" ? tenantFilter : null);
    setBots(nextBots);
  }

  function handleDelete(bot: BotProfile) {
    setSubmitError(null);
    setSubmitMessage(null);
    const confirmed = window.confirm(`确定删除机器人「${bot.name}」吗？这会删除它的 FAQ、知识页、会话记录，并注销 Telegram webhook。`);
    if (!confirmed) {
      return;
    }

    startTransition(async () => {
      try {
        await api.deleteBotProfile(bot.id);
        if (editingBotId === bot.id) {
          resetForm();
        }
        await reloadBots();
        setSubmitMessage("机器人已删除，并已注销 Telegram webhook。");
      } catch (deleteFailure) {
        if (deleteFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(deleteFailure instanceof Error ? deleteFailure.message : "机器人删除失败");
      }
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitMessage(null);

    if (!form.name.trim()) {
      setSubmitError("机器人名称不能为空。");
      return;
    }
    if (!form.telegram_bot_token.trim()) {
      setSubmitError("机器人 API Token 不能为空。");
      return;
    }
    if (!form.tenant_id.trim()) {
      setSubmitError("请选择所属客户。");
      return;
    }

    startTransition(async () => {
      try {
        const basePayload: BotProfileCreatePayload = {
          tenant_id: form.tenant_id,
          name: form.name.trim(),
          telegram_bot_token: form.telegram_bot_token.trim(),
          telegram_bot_username: normalizeUsername(form.telegram_bot_username) || null,
          support_group_chat_id: form.support_group_chat_id.trim() || null,
          welcome_message: form.welcome_message.trim() || DEFAULT_WELCOME_MESSAGE,
          unanswered_fallback_message: form.unanswered_fallback_message.trim() || DEFAULT_UNANSWERED_FALLBACK_MESSAGE,
          email_auto_reply_enabled: form.email_auto_reply_enabled,
          email_auto_reply_message: form.email_auto_reply_message.trim() || DEFAULT_EMAIL_AUTO_REPLY_MESSAGE,
          language: form.language.trim() || "zh",
          industry: form.industry.trim() || null,
          high_risk_keywords_json: splitText(form.high_risk_keywords_text),
          sensitive_keywords_json: splitText(form.sensitive_keywords_text),
          is_active: form.is_active
        };
        const botDescription = form.telegram_bot_description.trim();
        if (botDescription) {
          basePayload.telegram_bot_description = botDescription;
        }

        if (editingBotId) {
          const payload: BotProfileUpdatePayload = basePayload;
          await api.updateBotProfile(editingBotId, payload);
          setSubmitMessage("机器人配置已更新；启用状态下会自动注册 Telegram webhook。");
        } else {
          const payload: BotProfileCreatePayload = basePayload;
          await api.createBotProfile(payload);
          setSubmitMessage("机器人配置已创建；启用状态下会自动注册 Telegram webhook。");
        }

        await reloadBots();
        resetForm();
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(submitFailure instanceof Error ? submitFailure.message : "机器人配置保存失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel
        title="机器人配置说明"
        description="这页用于维护多个 Telegram Bot、对应客服群，以及每个 Bot 自己的人工分流词。"
      >
        <div className="grid faq-guide-grid">
          {BOT_GUIDE.map((item) => (
            <div key={item.title} className="card">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel
        title={editingBotId ? "编辑机器人配置" : "新增机器人配置"}
        description="机器人分流顺序固定为：先看人工词，再查 FAQ，再查知识页，最后才澄清。FAQ/知识页/风格配置页都会基于这里选中的 Bot 工作。"
      >
        {error ? <p className="error-text">{error}</p> : null}
        {!error ? (
          <form className="stack" onSubmit={handleSubmit}>
            {isSuperAdmin ? (
              <label>
                所属客户
                <select value={form.tenant_id} onChange={(event) => updateForm("tenant_id", event.target.value)}>
                  {tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <div className="grid faq-form-grid">
              <label>
                机器人名称
                <input type="text" value={form.name} onChange={(event) => updateForm("name", event.target.value)} placeholder="例如：销售咨询 Bot" />
              </label>
              <label>
                机器人用户名
                <input
                  type="text"
                  value={form.telegram_bot_username}
                  onChange={(event) => updateForm("telegram_bot_username", event.target.value)}
                  placeholder="例如：support_bot"
                />
              </label>
            </div>

            <label>
              机器人 API Token
              <input
                type="text"
                value={form.telegram_bot_token}
                onChange={(event) => updateForm("telegram_bot_token", event.target.value)}
                placeholder="填写 BotFather 提供的 token"
              />
            </label>

            <label>
              欢迎语（/start）
              <textarea
                rows={4}
                value={form.welcome_message}
                onChange={(event) => updateForm("welcome_message", event.target.value)}
                placeholder="用户发送 /start 时，机器人会回复这里的内容"
              />
            </label>

            <label>
              兜底回复（普通 Bot 私聊未命中）
              <textarea
                rows={3}
                value={form.unanswered_fallback_message}
                onChange={(event) => updateForm("unanswered_fallback_message", event.target.value)}
                placeholder={DEFAULT_UNANSWERED_FALLBACK_MESSAGE}
              />
            </label>

            <div className="card">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.email_auto_reply_enabled}
                  onChange={(event) => updateForm("email_auto_reply_enabled", event.target.checked)}
                />
                <span>启用邮箱格式自动回复</span>
              </label>
              <p>当用户消息里包含邮箱地址时，机器人会直接回复下面这段内容；如果关闭开关，则继续走 FAQ/知识页流程。</p>
            </div>

            <label>
              邮箱自动回复内容
              <textarea
                rows={3}
                value={form.email_auto_reply_message}
                onChange={(event) => updateForm("email_auto_reply_message", event.target.value)}
                placeholder={DEFAULT_EMAIL_AUTO_REPLY_MESSAGE}
              />
            </label>

            <label>
              Bot Description（同步到 Telegram）
              <textarea
                rows={3}
                value={form.telegram_bot_description}
                onChange={(event) => updateForm("telegram_bot_description", event.target.value)}
                placeholder="填写后保存，会同步到 Telegram；留空不修改"
              />
            </label>
            <div className="button-row">
              <button
                type="button"
                className="button-secondary"
                onClick={loadTelegramDescription}
                disabled={!editingBotId || isPending || isDescriptionLoading}
              >
                {isDescriptionLoading ? "读取中..." : "读取当前 Description"}
              </button>
            </div>

            <div className="grid faq-form-grid">
              <label>
                对应客服群 Chat ID
                <input
                  type="text"
                  value={form.support_group_chat_id}
                  onChange={(event) => updateForm("support_group_chat_id", event.target.value)}
                  placeholder="例如：-1001234567890"
                />
              </label>
              <label>
                语言
                <input type="text" value={form.language} onChange={(event) => updateForm("language", event.target.value)} placeholder="例如：zh" />
              </label>
            </div>

            <label>
              行业/场景
              <input type="text" value={form.industry} onChange={(event) => updateForm("industry", event.target.value)} placeholder="例如：saas" />
            </label>

            <div className="grid faq-form-grid">
              <label>
                高风险词
                <textarea
                  rows={4}
                  value={form.high_risk_keywords_text}
                  onChange={(event) => updateForm("high_risk_keywords_text", event.target.value)}
                  placeholder={"人工\n退款\n投诉"}
                />
              </label>
              <label>
                敏感词
                <textarea
                  rows={4}
                  value={form.sensitive_keywords_text}
                  onChange={(event) => updateForm("sensitive_keywords_text", event.target.value)}
                  placeholder={"骂\n骗\n垃圾"}
                />
              </label>
            </div>

            <div className="card">
              <strong>Business Bot 接入模式</strong>
              <p>这个 Bot 可同时处理普通 Bot 私聊和 Telegram Business 账号授权后的私聊。Business 账号连接成功后，客户看到的自动回复会以该业务账号名义发出。</p>
              <p>Business 私聊只会自动回复 FAQ 或知识库命中的答案；未命中或触发人工词时，不会私聊兜底回复，也不会转发到客服群。</p>
              <p>配置步骤：BotFather 开启 Business Mode；Telegram Business 账号在设置中连接这个 Bot；授权可访问的私聊范围、读取消息和回复权限。</p>
            </div>

            <div className="card">
              <strong>当前回答顺序</strong>
              <p>人工词命中后直接转人工；其他消息不再靠关键词判断 FAQ 或知识页，而是固定先查 FAQ，再查知识页，最后才澄清。</p>
            </div>

            <label className="checkbox-row">
              <input type="checkbox" checked={form.is_active} onChange={(event) => updateForm("is_active", event.target.checked)} />
              <span>启用这个机器人</span>
            </label>

            <div className="card">
              <strong>Webhook 自动注册</strong>
              <p>保存启用状态的机器人后，系统会自动向 Telegram 注册 webhook。</p>
              <p>
                当前将注册到：
                {form.telegram_bot_username.trim()
                  ? ` ${exampleWebhookBase}/${normalizeUsername(form.telegram_bot_username)}`
                  : " 先填写机器人用户名；如果为空，后端会使用 Bot Profile ID。"}
              </p>
            </div>

            {submitMessage ? <p className="success-text">{submitMessage}</p> : null}
            {submitError ? <p className="error-text">{submitError}</p> : null}
            <div className="button-row">
              <button type="submit" disabled={isPending}>
                {isPending ? "保存中..." : editingBotId ? "保存配置" : "创建机器人"}
              </button>
              <button type="button" className="button-secondary" onClick={resetForm} disabled={isPending}>
                {editingBotId ? "取消编辑" : "清空表单"}
              </button>
            </div>
          </form>
        ) : null}
      </Panel>

      <Panel title="机器人列表" description="超级管理员可按客户筛选；客户管理员只会看到自己名下的 Bot。">
        {isSuperAdmin ? (
          <div className="card">
            <label>
              客户筛选
              <select value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)}>
                <option value="all">全部客户</option>
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
        {isLoading ? <p className="muted">加载中...</p> : null}
        {!isLoading ? (
          <div className="bot-profile-list">
            {bots.length === 0 ? <p className="muted">暂无机器人配置。</p> : null}
            {bots.map((bot) => (
              <article key={bot.id} className="bot-profile-card">
                <div className="bot-profile-card-header">
                  <div>
                    <div className="bot-profile-title-row">
                      <h3>{bot.name}</h3>
                      <span className={`badge${bot.is_active ? "" : " badge-muted"}`}>{bot.is_active ? "active" : "inactive"}</span>
                    </div>
                    <div className="table-subtext">ID: {bot.id}</div>
                  </div>
                  <div className="bot-profile-actions">
                    <button type="button" className="button-secondary button-inline" onClick={() => startEdit(bot)} disabled={isPending}>
                      编辑
                    </button>
                    <button type="button" className="button-danger button-inline" onClick={() => handleDelete(bot)} disabled={isPending}>
                      删除
                    </button>
                  </div>
                </div>

                <div className="bot-profile-meta-grid">
                  <div className="bot-profile-meta-item">
                    <span>所属客户</span>
                    <strong>{bot.tenant_name ?? bot.tenant_id}</strong>
                  </div>
                  <div className="bot-profile-meta-item">
                    <span>用户名</span>
                    <strong>{bot.telegram_bot_username ? `@${bot.telegram_bot_username.replace(/^@+/, "")}` : "未填写"}</strong>
                  </div>
                  <div className="bot-profile-meta-item">
                    <span>客服群</span>
                    <strong>{bot.support_group_chat_id ?? "未填写"}</strong>
                  </div>
                  <div className="bot-profile-meta-item">
                    <span>Business 接入</span>
                    <strong>
                      <span className={`badge${bot.business_connection_status === "ready" ? "" : " badge-muted"}`}>
                        {businessConnectionLabel(bot)}
                      </span>
                    </strong>
                    {bot.business_connection_id ? <div className="table-subtext">ID: {bot.business_connection_id}</div> : null}
                  </div>
                </div>

                <div className="bot-profile-section">
                  <span className="bot-profile-section-label">欢迎语</span>
                  <p className="bot-profile-message">{bot.welcome_message}</p>
                </div>

                <div className="bot-profile-section">
                  <span className="bot-profile-section-label">兜底回复</span>
                  <p className="bot-profile-message">{bot.unanswered_fallback_message}</p>
                </div>

                <div className="bot-profile-section">
                  <span className="bot-profile-section-label">邮箱自动回复</span>
                  <p className="bot-profile-message">
                    {bot.email_auto_reply_enabled ? bot.email_auto_reply_message : "已关闭"}
                  </p>
                </div>

                <div className="bot-profile-keyword-grid">
                  <div className="bot-profile-section">
                    <span className="bot-profile-section-label">高风险词</span>
                    <div className="bot-profile-chip-row">
                      {bot.high_risk_keywords_json.length
                        ? bot.high_risk_keywords_json.map((keyword) => (
                            <span key={keyword} className="keyword-chip keyword-chip-danger">
                              {keyword}
                            </span>
                          ))
                        : <span className="muted">未设置</span>}
                    </div>
                  </div>
                  <div className="bot-profile-section">
                    <span className="bot-profile-section-label">敏感词</span>
                    <div className="bot-profile-chip-row">
                      {bot.sensitive_keywords_json.length
                        ? bot.sensitive_keywords_json.map((keyword) => (
                            <span key={keyword} className="keyword-chip">
                              {keyword}
                            </span>
                          ))
                        : <span className="muted">未设置</span>}
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
