"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { BotScopePicker } from "@/components/bot-scope-picker";
import { HelpTooltip } from "@/components/help-tooltip";
import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { BotProfile, CurrentUser, FAQCreatePayload, FAQEntry, FAQUpdatePayload, RiskLevel } from "@/types/api";

interface FAQFormState {
  questionPatternsText: string;
  canonical_answer: string;
  risk_level: RiskLevel;
  priority: number;
  status: string;
}

const DEFAULT_FORM: FAQFormState = {
  questionPatternsText: "",
  canonical_answer: "",
  risk_level: "low",
  priority: 100,
  status: "active"
};

const FIELD_GUIDE = [
  {
    title: "问题模式",
    description: "写用户真实会说的话。每行一个，优先录高频短语，不要堆太多同义词。"
  },
  {
    title: "标准答案",
    description: "写事实正确、可直接发出的回复。不要写需要模型自由发挥的空话。"
  },
  {
    title: "风险",
    description: "不是难度，而是答错后的业务后果。普通介绍用 low；容易引发争议的规则类问题用 medium；退款、赔偿、合同、账号安全、数据删除这类尽量不要做自动 FAQ，或至少标 high。"
  },
  {
    title: "优先级",
    description: "数字越小越优先命中。核心 FAQ 可设 10；普通 FAQ 可设 50 到 100；兜底 FAQ 设更大。"
  },
  {
    title: "状态",
    description: "active 表示机器人会使用；inactive 表示保留但不参与线上命中。临时下线先改状态，不要直接删。"
  }
] as const;

const RISK_TOOLTIP =
  "表示这条 FAQ 对业务风险的敏感程度，不是问题难度。low 适合价格、功能、试用；medium 适合时效或规则边界；high 适合退款、赔偿、合同、账号安全、数据删除。";
const PRIORITY_TOOLTIP =
  "当一条消息可能同时命中多条 FAQ 时，用它决定先选哪条。数字越小优先级越高，10 会比 100 更先被命中。";
const STATUS_TOOLTIP =
  "active 表示启用，机器人会使用；inactive 表示停用，保留数据但不参与线上回复。";

function patternsTextToList(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function faqToFormState(faq: FAQEntry): FAQFormState {
  return {
    questionPatternsText: faq.question_patterns_json.join("\n"),
    canonical_answer: faq.canonical_answer,
    risk_level: faq.risk_level,
    priority: faq.priority,
    status: faq.status
  };
}

export default function FAQsPage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [bots, setBots] = useState<BotProfile[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<string>("");
  const [faqs, setFaqs] = useState<FAQEntry[]>([]);
  const [form, setForm] = useState<FAQFormState>(DEFAULT_FORM);
  const [editingFaqId, setEditingFaqId] = useState<string | null>(null);
  const [confirmDeleteFaqId, setConfirmDeleteFaqId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedBot = bots.find((bot) => bot.id == selectedBotId) ?? null;

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
        setError(loadError instanceof Error ? loadError.message : "FAQ 加载失败");
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
      setFaqs([]);
      return;
    }

    let cancelled = false;

    async function loadFaqs() {
      try {
        const faqData = await api.faqs(selectedBotId);
        if (cancelled) {
          return;
        }
        setFaqs(faqData);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "FAQ 加载失败");
      }
    }

    void loadFaqs();
    return () => {
      cancelled = true;
    };
  }, [router, selectedBotId]);

  function updateForm<K extends keyof FAQFormState>(key: K, value: FAQFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function resetForm() {
    setEditingFaqId(null);
    setConfirmDeleteFaqId(null);
    setForm(DEFAULT_FORM);
    setSubmitError(null);
    setSubmitMessage(null);
  }

  function startEdit(faq: FAQEntry) {
    setEditingFaqId(faq.id);
    setForm(faqToFormState(faq));
    setSubmitError(null);
    setSubmitMessage(null);
  }

  async function reloadFaqs() {
    if (!selectedBotId) {
      return;
    }
    const nextFaqs = await api.faqs(selectedBotId);
    setFaqs(nextFaqs);
  }

  function handleDelete(faq: FAQEntry) {
    setSubmitError(null);
    setSubmitMessage(null);

    startTransition(async () => {
      try {
        await api.deleteFaq(faq.id);
        await reloadFaqs();
        setConfirmDeleteFaqId(null);
        if (editingFaqId === faq.id) {
          setEditingFaqId(null);
          setForm(DEFAULT_FORM);
        }
        setSubmitMessage("FAQ 已删除。");
      } catch (deleteFailure) {
        if (deleteFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(deleteFailure instanceof Error ? deleteFailure.message : "FAQ 删除失败");
      }
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitMessage(null);

    const questionPatterns = patternsTextToList(form.questionPatternsText);
    if (!selectedBot) {
      setSubmitError("请先选择一个机器人。");
      return;
    }
    if (questionPatterns.length === 0) {
      setSubmitError("至少填写一个问题模式。");
      return;
    }
    if (!form.canonical_answer.trim()) {
      setSubmitError("标准答案不能为空。");
      return;
    }

    startTransition(async () => {
      try {
        if (editingFaqId) {
          const payload: FAQUpdatePayload = {
            question_patterns_json: questionPatterns,
            canonical_answer: form.canonical_answer.trim(),
            risk_level: form.risk_level,
            priority: form.priority,
            status: form.status
          };
          await api.updateFaq(editingFaqId, payload);
          setSubmitMessage("FAQ 已更新。");
        } else {
          const payload: FAQCreatePayload = {
            bot_profile_id: selectedBot.id,
            tenant_id: selectedBot.tenant_id,
            question_patterns_json: questionPatterns,
            canonical_answer: form.canonical_answer.trim(),
            risk_level: form.risk_level,
            priority: form.priority,
            status: form.status
          };
          await api.createFaq(payload);
          setSubmitMessage("FAQ 已创建。");
        }

        await reloadFaqs();
        setEditingFaqId(null);
        setForm(DEFAULT_FORM);
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(submitFailure instanceof Error ? submitFailure.message : "FAQ 提交失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel title="FAQ 字段填写规范" description="先写高频、事实明确、低风险的问题。复杂规则和高风险话题优先转人工。">
        <div className="grid faq-guide-grid">
          {FIELD_GUIDE.map((item) => (
            <div key={item.title} className="card">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
          ))}
        </div>
        <div className="card">
          <strong>当前回答顺序</strong>
          <p>机器人会先查 FAQ，再查知识页，最后才澄清。所以 FAQ 适合放高频、短答案、希望优先命中的问题。</p>
        </div>
      </Panel>

      {me ? (
        <BotScopePicker
          bots={bots}
          value={selectedBotId}
          onChange={(botProfileId) => {
            setSelectedBotId(botProfileId);
            resetForm();
          }}
          disabled={isPending}
        />
      ) : null}

      <Panel
        title={editingFaqId ? "编辑 FAQ" : "新增 FAQ"}
        description="FAQ 用于短问短答和优先命中。当前表单会保存到你上面选中的机器人。"
      >
        {error ? <p className="error-text">{error}</p> : null}
        {!error ? (
          <form className="stack" onSubmit={handleSubmit}>
            <label>
              问题模式
              <textarea
                rows={4}
                value={form.questionPatternsText}
                onChange={(event) => updateForm("questionPatternsText", event.target.value)}
                placeholder={"价格\n套餐\n收费"}
              />
            </label>
            <label>
              标准答案
              <textarea
                rows={5}
                value={form.canonical_answer}
                onChange={(event) => updateForm("canonical_answer", event.target.value)}
                placeholder="输入标准回复内容"
              />
            </label>
            <div className="grid faq-form-grid faq-form-grid-narrow">
              <label>
                <span className="label-with-help">
                  风险等级
                  <HelpTooltip label="风险" content={RISK_TOOLTIP} />
                </span>
                <select value={form.risk_level} onChange={(event) => updateForm("risk_level", event.target.value as RiskLevel)}>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
              <label>
                <span className="label-with-help">
                  优先级
                  <HelpTooltip label="优先级" content={PRIORITY_TOOLTIP} />
                </span>
                <input
                  type="number"
                  value={form.priority}
                  onChange={(event) => updateForm("priority", Number(event.target.value) || 0)}
                />
              </label>
              <label>
                <span className="label-with-help">
                  状态
                  <HelpTooltip label="状态" content={STATUS_TOOLTIP} />
                </span>
                <select value={form.status} onChange={(event) => updateForm("status", event.target.value)}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
            </div>
            {submitError ? <p className="error-text">{submitError}</p> : null}
            {submitMessage ? <p className="success-text">{submitMessage}</p> : null}
            <div className="button-row">
              <button type="submit" disabled={isPending || isLoading || !selectedBotId}>
                {isPending ? "提交中..." : editingFaqId ? "保存 FAQ" : "创建 FAQ"}
              </button>
              {editingFaqId ? (
                <button type="button" className="button-secondary" onClick={resetForm} disabled={isPending}>
                  取消编辑
                </button>
              ) : null}
            </div>
          </form>
        ) : null}
      </Panel>

      <Panel title="FAQ 列表" description="列表会按当前选中的机器人切换。FAQ 没命中时，机器人才会继续去知识页找答案。">
        {isLoading ? <p className="muted">加载中...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!isLoading && !error ? (
          <table>
            <thead>
              <tr>
                <th>问题模式</th>
                <th>标准答案</th>
                <th>
                  <span className="label-with-help">
                    风险
                    <HelpTooltip label="风险" content={RISK_TOOLTIP} />
                  </span>
                </th>
                <th>
                  <span className="label-with-help">
                    优先级
                    <HelpTooltip label="优先级" content={PRIORITY_TOOLTIP} />
                  </span>
                </th>
                <th>
                  <span className="label-with-help">
                    状态
                    <HelpTooltip label="状态" content={STATUS_TOOLTIP} />
                  </span>
                </th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {faqs.map((faq) => (
                <tr key={faq.id}>
                  <td>{faq.question_patterns_json.join(" / ")}</td>
                  <td>{faq.canonical_answer}</td>
                  <td>{faq.risk_level}</td>
                  <td>{faq.priority}</td>
                  <td>{faq.status}</td>
                  <td>
                    <div className="button-row">
                      <button type="button" className="button-secondary button-inline" onClick={() => startEdit(faq)}>
                        编辑
                      </button>
                      {confirmDeleteFaqId === faq.id ? (
                        <>
                          <button type="button" className="button-danger button-inline" onClick={() => handleDelete(faq)} disabled={isPending}>
                            确认删除
                          </button>
                          <button type="button" className="button-secondary button-inline" onClick={() => setConfirmDeleteFaqId(null)} disabled={isPending}>
                            取消
                          </button>
                        </>
                      ) : (
                        <button type="button" className="button-danger button-inline" onClick={() => setConfirmDeleteFaqId(faq.id)}>
                          删除
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Panel>
    </div>
  );
}
