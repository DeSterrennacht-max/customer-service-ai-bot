"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { BotScopePicker } from "@/components/bot-scope-picker";
import { ImageAssetManager } from "@/components/image-asset-manager";
import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { BotProfile, CurrentUser, ImageAsset, KnowledgePage, KnowledgePageCreatePayload, KnowledgePageUpdatePayload, RiskLevel } from "@/types/api";

interface KnowledgeFormState {
  title: string;
  body_markdown: string;
  image_assets_json: ImageAsset[];
  tagsText: string;
  risk_level: RiskLevel;
  status: string;
}

const DEFAULT_FORM: KnowledgeFormState = {
  title: "",
  body_markdown: "",
  image_assets_json: [],
  tagsText: "",
  risk_level: "low",
  status: "active"
};

const KNOWLEDGE_GUIDE = [
  {
    title: "标题",
    description: "写主题名，不要写成一句完整回复。适合功能说明、流程说明、政策说明。"
  },
  {
    title: "正文",
    description: "用 Markdown 录入项目资料。尽量按小节分段，事实写全，方便后续切块检索。"
  },
  {
    title: "标签",
    description: "写检索辅助词，例如 onboarding、login、pricing、refund-policy。支持逗号或换行分隔。"
  },
  {
    title: "风险 / 状态",
    description: "风险的含义和 FAQ 一致；状态 active 才会参与线上检索，inactive 只保留不启用。"
  }
] as const;

function tagsTextToList(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function knowledgePageToForm(page: KnowledgePage): KnowledgeFormState {
  return {
    title: page.title,
    body_markdown: page.body_markdown,
    image_assets_json: page.image_assets_json ?? [],
    tagsText: page.tags_json.join("\n"),
    risk_level: page.risk_level,
    status: page.status
  };
}

function summarizeMarkdown(markdown: string): string {
  return markdown.replace(/\s+/g, " ").trim().slice(0, 120);
}

export default function KnowledgePagesPage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [bots, setBots] = useState<BotProfile[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<string>("");
  const [pages, setPages] = useState<KnowledgePage[]>([]);
  const [form, setForm] = useState<KnowledgeFormState>(DEFAULT_FORM);
  const [editingPageId, setEditingPageId] = useState<string | null>(null);
  const [confirmDeletePageId, setConfirmDeletePageId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedBot = bots.find((bot) => bot.id === selectedBotId) ?? null;

  useEffect(() => {
    let cancelled = false;

    async function loadBots() {
      try {
        const [currentUser, botData] = await Promise.all([api.me(), api.botProfiles()]);
        if (cancelled) {
          return;
        }
        setMe(currentUser);
        setBots(botData);
        if (botData[0]) {
          setSelectedBotId((current) => current || botData[0].id);
        }
        setError(null);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "知识页加载失败");
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
  }, [router]);

  useEffect(() => {
    if (!selectedBotId) {
      setPages([]);
      return;
    }

    let cancelled = false;

    async function loadPages() {
      try {
        const knowledgePages = await api.knowledgePages(selectedBotId);
        if (cancelled) {
          return;
        }
        setPages(knowledgePages);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "知识页加载失败");
      }
    }

    void loadPages();
    return () => {
      cancelled = true;
    };
  }, [router, selectedBotId]);

  function updateForm<K extends keyof KnowledgeFormState>(key: K, value: KnowledgeFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function cleanupUnsavedImages() {
    const originalPage = editingPageId ? pages.find((page) => page.id === editingPageId) : null;
    const persistedKeys = new Set((originalPage?.image_assets_json ?? []).map((asset) => asset.object_key));
    const pendingAssets = form.image_assets_json.filter((asset) => !persistedKeys.has(asset.object_key));
    if (pendingAssets.length) {
      void Promise.allSettled(pendingAssets.map((asset) => api.deleteImage(asset.object_key)));
    }
  }

  function resetForm(cleanupImages = false) {
    if (cleanupImages) {
      cleanupUnsavedImages();
    }
    setEditingPageId(null);
    setConfirmDeletePageId(null);
    setForm(DEFAULT_FORM);
    setSubmitError(null);
    setSubmitMessage(null);
  }

  function startEdit(page: KnowledgePage) {
    setEditingPageId(page.id);
    setForm(knowledgePageToForm(page));
    setSubmitError(null);
    setSubmitMessage(null);
  }

  async function reloadKnowledgePages() {
    if (!selectedBotId) {
      return;
    }
    const nextPages = await api.knowledgePages(selectedBotId);
    setPages(nextPages);
  }

  function isPersistedImage(asset: ImageAsset): boolean {
    if (!editingPageId) {
      return false;
    }
    const originalPage = pages.find((page) => page.id === editingPageId);
    return Boolean(originalPage?.image_assets_json?.some((item) => item.object_key === asset.object_key));
  }

  function handleImageUpload(file: File) {
    setSubmitError(null);
    setSubmitMessage(null);
    if (!selectedBot) {
      setSubmitError("请先选择一个机器人。");
      return;
    }

    startTransition(async () => {
      try {
        const asset = await api.uploadImage(selectedBot.id, "knowledge_page", file);
        setForm((current) => ({ ...current, image_assets_json: [...current.image_assets_json, asset] }));
        setSubmitMessage("图片已上传。保存知识页后会随答案一起生效。");
      } catch (uploadFailure) {
        if (uploadFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(uploadFailure instanceof Error ? uploadFailure.message : "图片上传失败");
      }
    });
  }

  function handleImageRemove(asset: ImageAsset) {
    setSubmitError(null);
    setSubmitMessage(null);
    setForm((current) => ({
      ...current,
      image_assets_json: current.image_assets_json.filter((item) => item.object_key !== asset.object_key)
    }));

    if (isPersistedImage(asset)) {
      setSubmitMessage("图片已从表单移除，保存知识页后会同步删除 R2 原图。");
      return;
    }

    startTransition(async () => {
      try {
        await api.deleteImage(asset.object_key);
        setSubmitMessage("图片已删除。");
      } catch (deleteFailure) {
        if (deleteFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(deleteFailure instanceof Error ? deleteFailure.message : "图片删除失败");
      }
    });
  }

  function handleDelete(page: KnowledgePage) {
    setSubmitError(null);
    setSubmitMessage(null);

    startTransition(async () => {
      try {
        await api.deleteKnowledgePage(page.id);
        await reloadKnowledgePages();
        setConfirmDeletePageId(null);
        if (editingPageId === page.id) {
          setEditingPageId(null);
          setForm(DEFAULT_FORM);
        }
        setSubmitMessage("知识页已删除。");
      } catch (deleteFailure) {
        if (deleteFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(deleteFailure instanceof Error ? deleteFailure.message : "知识页删除失败");
      }
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitMessage(null);

    const tags = tagsTextToList(form.tagsText);
    if (!selectedBot) {
      setSubmitError("请先选择一个机器人。");
      return;
    }
    if (!form.title.trim()) {
      setSubmitError("标题不能为空。");
      return;
    }
    if (!form.body_markdown.trim()) {
      setSubmitError("正文不能为空。");
      return;
    }

    startTransition(async () => {
      try {
        if (editingPageId) {
          const payload: KnowledgePageUpdatePayload = {
            title: form.title.trim(),
            body_markdown: form.body_markdown.trim(),
            image_assets_json: form.image_assets_json,
            tags_json: tags,
            risk_level: form.risk_level,
            status: form.status
          };
          await api.updateKnowledgePage(editingPageId, payload);
          setSubmitMessage("知识页已更新。");
        } else {
          const payload: KnowledgePageCreatePayload = {
            bot_profile_id: selectedBot.id,
            tenant_id: selectedBot.tenant_id,
            title: form.title.trim(),
            body_markdown: form.body_markdown.trim(),
            image_assets_json: form.image_assets_json,
            tags_json: tags,
            risk_level: form.risk_level,
            status: form.status
          };
          await api.createKnowledgePage(payload);
          setSubmitMessage("知识页已创建。");
        }

        await reloadKnowledgePages();
        setEditingPageId(null);
        setForm(DEFAULT_FORM);
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(submitFailure instanceof Error ? submitFailure.message : "知识页提交失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel title="知识页填写规范" description="知识页适合录入中长篇资料、链接、地址、下载说明。系统会自动切块，作为 FAQ 之后的兜底答案来源。">
        <div className="grid faq-guide-grid">
          {KNOWLEDGE_GUIDE.map((item) => (
            <div key={item.title} className="card">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
          ))}
        </div>
        <div className="card">
          <strong>当前回答顺序</strong>
          <p>机器人不会先查知识页，而是先查 FAQ。只有 FAQ 没命中时，才会来知识页里找最相关的小节回复给客户。</p>
        </div>
      </Panel>

      {me ? (
        <BotScopePicker
          bots={bots}
          value={selectedBotId}
          onChange={(botProfileId) => {
            setSelectedBotId(botProfileId);
            resetForm(true);
          }}
          disabled={isPending}
        />
      ) : null}

      <Panel title={editingPageId ? "编辑知识页" : "新增知识页"} description="保存后会自动重建知识切块，内容只会写入当前选中的机器人，并在 FAQ 未命中时参与回复。">
        {error ? <p className="error-text">{error}</p> : null}
        {!error ? (
          <form className="stack" onSubmit={handleSubmit}>
            <label>
              标题
              <input
                type="text"
                value={form.title}
                onChange={(event) => updateForm("title", event.target.value)}
                placeholder="例如：登录与账号常见问题"
              />
            </label>
            <label>
              正文（Markdown）
              <textarea
                rows={12}
                value={form.body_markdown}
                onChange={(event) => updateForm("body_markdown", event.target.value)}
                placeholder={"## 登录失败\n- 检查邮箱是否填写正确\n- 检查验证码是否过期\n\n## 忘记密码\n点击登录页的“忘记密码”即可重置。"}
              />
            </label>
            <label>
              标签
              <textarea
                rows={4}
                value={form.tagsText}
                onChange={(event) => updateForm("tagsText", event.target.value)}
                placeholder={"login\naccount\npassword"}
              />
            </label>
            <div className="grid faq-form-grid faq-form-grid-narrow">
              <label>
                风险等级
                <select value={form.risk_level} onChange={(event) => updateForm("risk_level", event.target.value as RiskLevel)}>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
              <label>
                状态
                <select value={form.status} onChange={(event) => updateForm("status", event.target.value)}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
            </div>
            <ImageAssetManager assets={form.image_assets_json} disabled={isPending || !selectedBotId} onUpload={handleImageUpload} onRemove={handleImageRemove} />
            {submitError ? <p className="error-text">{submitError}</p> : null}
            {submitMessage ? <p className="success-text">{submitMessage}</p> : null}
            <div className="button-row">
              <button type="submit" disabled={isPending || isLoading || !selectedBotId}>
                {isPending ? "提交中..." : editingPageId ? "保存知识页" : "创建知识页"}
              </button>
              {editingPageId ? (
                <button type="button" className="button-secondary" onClick={() => resetForm(true)} disabled={isPending}>
                  取消编辑
                </button>
              ) : null}
            </div>
          </form>
        ) : null}
      </Panel>

      <Panel title="知识页列表" description="列表会按当前选中的机器人切换；点击“编辑”会把现有内容回填到表单里。知识页适合放完整资料，不适合放一句话短答。">
        {isLoading ? <p className="muted">加载中...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!isLoading && !error ? (
          <div className="content-card-list">
            {pages.length === 0 ? <p className="muted">暂无知识页。</p> : null}
            {pages.map((page) => (
              <article key={page.id} className="content-card">
                <div className="content-card-header">
                  <div className="content-card-heading">
                    <span className="content-card-eyebrow">标题</span>
                    <h3>{page.title}</h3>
                  </div>
                  <div className="content-card-actions">
                    <button type="button" className="button-secondary button-inline" onClick={() => startEdit(page)}>
                      编辑
                    </button>
                    {confirmDeletePageId === page.id ? (
                      <>
                        <button type="button" className="button-danger button-inline" onClick={() => handleDelete(page)} disabled={isPending}>
                          确认删除
                        </button>
                        <button type="button" className="button-secondary button-inline" onClick={() => setConfirmDeletePageId(null)} disabled={isPending}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button type="button" className="button-danger button-inline" onClick={() => setConfirmDeletePageId(page.id)}>
                        删除
                      </button>
                    )}
                  </div>
                </div>

                <div className="content-text-block">
                  <span className="content-card-eyebrow">正文摘要</span>
                  <p>{summarizeMarkdown(page.body_markdown) || "暂无摘要"}</p>
                </div>

                <div className="content-section">
                  <span className="content-card-eyebrow">标签</span>
                  <div className="content-chip-row">
                    {page.tags_json.length
                      ? page.tags_json.map((tag) => (
                          <span key={tag} className="content-chip">
                            {tag}
                          </span>
                        ))
                      : <span className="muted">未设置</span>}
                  </div>
                </div>

                <div className="content-section">
                  <span className="content-card-eyebrow">图片回复</span>
                  {page.image_assets_json?.length ? (
                    <div className="content-chip-row">
                      {page.image_assets_json.map((asset) => (
                        <a key={asset.object_key} className="content-chip" href={asset.url} target="_blank" rel="noreferrer">
                          {asset.filename}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <span className="muted">未设置</span>
                  )}
                </div>

                <div className="content-meta-grid">
                  <div className="content-meta-item">
                    <span>风险</span>
                    <strong>
                      <span className={`badge${page.risk_level === "high" ? " badge-danger" : page.risk_level === "low" ? " badge-muted" : ""}`}>
                        {page.risk_level}
                      </span>
                    </strong>
                  </div>
                  <div className="content-meta-item">
                    <span>状态</span>
                    <strong>
                      <span className={`badge${page.status === "active" ? "" : " badge-muted"}`}>{page.status}</span>
                    </strong>
                  </div>
                  <div className="content-meta-item">
                    <span>更新时间</span>
                    <strong>{page.updated_at}</strong>
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
