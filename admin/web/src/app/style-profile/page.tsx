"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { BotScopePicker } from "@/components/bot-scope-picker";
import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { BotProfile, CurrentUser, StyleProfile, StyleProfileUpdatePayload } from "@/types/api";

interface StyleProfileFormState {
  tone: string;
  persona_notes: string;
  bannedPhrasesText: string;
  delay_min_ms: number;
  delay_max_ms: number;
  typing_enabled: boolean;
  clarify_max_turns: number;
}

const DEFAULT_FORM: StyleProfileFormState = {
  tone: "",
  persona_notes: "",
  bannedPhrasesText: "",
  delay_min_ms: 1200,
  delay_max_ms: 2800,
  typing_enabled: true,
  clarify_max_turns: 1
};

const STYLE_GUIDE = [
  {
    title: "语气",
    description: "写回复的总体风格关键词，尽量简短明确，例如：专业、温和、简洁。"
  },
  {
    title: "客服人设",
    description: "写给模型的表达要求，告诉它应该怎么说、避免怎么说，尽量用中文描述。"
  },
  {
    title: "禁用词",
    description: "一行一个，填绝对不允许出现在回复里的词或短句，例如“作为 AI”“根据系统”。"
  },
  {
    title: "延迟与 typing",
    description: "控制发送前的拟人化延迟。最小值不能大于最大值；typing 打开后会先显示正在输入。"
  },
  {
    title: "澄清轮数",
    description: "表示信息不够时最多追问几轮。第一阶段建议控制在 1 到 2 轮，避免像脚本客服。"
  }
] as const;

function profileToForm(profile: StyleProfile): StyleProfileFormState {
  return {
    tone: profile.tone,
    persona_notes: profile.persona_notes ?? "",
    bannedPhrasesText: profile.banned_phrases_json?.join("\n") ?? "",
    delay_min_ms: profile.delay_min_ms,
    delay_max_ms: profile.delay_max_ms,
    typing_enabled: profile.typing_enabled,
    clarify_max_turns: profile.clarify_max_turns
  };
}

function bannedPhrasesTextToList(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function StyleProfilePage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [bots, setBots] = useState<BotProfile[]>([]);
  const [selectedBotId, setSelectedBotId] = useState<string>("");
  const [profile, setProfile] = useState<StyleProfile | null>(null);
  const [form, setForm] = useState<StyleProfileFormState>(DEFAULT_FORM);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

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
        setError(loadError instanceof Error ? loadError.message : "风格配置加载失败");
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
      setProfile(null);
      return;
    }

    let cancelled = false;

    async function loadStyleProfile() {
      try {
        const data = await api.styleProfile(selectedBotId);
        if (cancelled) {
          return;
        }
        setProfile(data);
        setForm(profileToForm(data));
        setError(null);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "风格配置加载失败");
      }
    }

    void loadStyleProfile();
    return () => {
      cancelled = true;
    };
  }, [router, selectedBotId]);

  function updateForm<K extends keyof StyleProfileFormState>(key: K, value: StyleProfileFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function resetForm() {
    if (!profile) {
      return;
    }
    setForm(profileToForm(profile));
    setSubmitError(null);
    setSubmitMessage(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitMessage(null);

    if (!selectedBotId) {
      setSubmitError("请先选择一个机器人。");
      return;
    }
    if (!form.tone.trim()) {
      setSubmitError("语气不能为空。");
      return;
    }

    if (form.delay_min_ms < 0 || form.delay_max_ms < 0) {
      setSubmitError("延迟不能小于 0。");
      return;
    }

    if (form.delay_min_ms > form.delay_max_ms) {
      setSubmitError("最小延迟不能大于最大延迟。");
      return;
    }

    if (form.clarify_max_turns < 0) {
      setSubmitError("澄清轮数不能小于 0。");
      return;
    }

    const payload: StyleProfileUpdatePayload = {
      bot_profile_id: selectedBotId,
      tone: form.tone.trim(),
      persona_notes: form.persona_notes.trim() || null,
      banned_phrases_json: bannedPhrasesTextToList(form.bannedPhrasesText),
      delay_min_ms: form.delay_min_ms,
      delay_max_ms: form.delay_max_ms,
      typing_enabled: form.typing_enabled,
      clarify_max_turns: form.clarify_max_turns
    };

    startTransition(async () => {
      try {
        const nextProfile = await api.updateStyleProfile(payload);
        setProfile(nextProfile);
        setForm(profileToForm(nextProfile));
        setSubmitMessage("风格配置已保存。");
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setSubmitError(submitFailure instanceof Error ? submitFailure.message : "风格配置保存失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel title="风格配置说明" description="这页控制机器人怎么说，而不是回答什么。尽量用中文写清楚要求，方便后面持续维护。">
        <div className="grid faq-guide-grid">
          {STYLE_GUIDE.map((item) => (
            <div key={item.title} className="card">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
          ))}
        </div>
      </Panel>

      {me ? (
        <BotScopePicker
          bots={bots}
          value={selectedBotId}
          onChange={(botProfileId) => {
            setSelectedBotId(botProfileId);
            setSubmitError(null);
            setSubmitMessage(null);
          }}
          disabled={isPending}
        />
      ) : null}

      <Panel title="编辑风格配置" description="保存后，新对话会按这里的风格生成回复。当前页面只会影响你上面选中的机器人。">
        {isLoading ? <p className="muted">加载中...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!isLoading && !error ? (
          <form className="stack" onSubmit={handleSubmit}>
            <label>
              语气
              <input
                type="text"
                value={form.tone}
                onChange={(event) => updateForm("tone", event.target.value)}
                placeholder="例如：专业、温和、简洁"
              />
            </label>

            <label>
              客服人设
              <textarea
                rows={5}
                value={form.persona_notes}
                onChange={(event) => updateForm("persona_notes", event.target.value)}
                placeholder="例如：默认用中文回复，语气自然，不要提自己是 AI，不要写成公文。"
              />
            </label>

            <label>
              禁用词
              <textarea
                rows={4}
                value={form.bannedPhrasesText}
                onChange={(event) => updateForm("bannedPhrasesText", event.target.value)}
                placeholder={"作为 AI\n根据系统\n机器人回复"}
              />
            </label>

            <div className="grid faq-form-grid faq-form-grid-narrow">
              <label>
                最小延迟（毫秒）
                <input
                  type="number"
                  min={0}
                  value={form.delay_min_ms}
                  onChange={(event) => updateForm("delay_min_ms", Number(event.target.value) || 0)}
                />
              </label>
              <label>
                最大延迟（毫秒）
                <input
                  type="number"
                  min={0}
                  value={form.delay_max_ms}
                  onChange={(event) => updateForm("delay_max_ms", Number(event.target.value) || 0)}
                />
              </label>
              <label>
                澄清轮数
                <input
                  type="number"
                  min={0}
                  value={form.clarify_max_turns}
                  onChange={(event) => updateForm("clarify_max_turns", Number(event.target.value) || 0)}
                />
              </label>
            </div>

            <label>
              <span className="label-with-help">typing 开关</span>
              <select
                value={form.typing_enabled ? "on" : "off"}
                onChange={(event) => updateForm("typing_enabled", event.target.value === "on")}
              >
                <option value="on">开启</option>
                <option value="off">关闭</option>
              </select>
            </label>

            {submitError ? <p className="error-text">{submitError}</p> : null}
            {submitMessage ? <p className="success-text">{submitMessage}</p> : null}

            <div className="button-row">
              <button type="submit" disabled={isPending || isLoading || !selectedBotId}>
                {isPending ? "保存中..." : "保存配置"}
              </button>
              <button type="button" className="button-secondary" onClick={resetForm} disabled={isPending || !profile}>
                恢复当前值
              </button>
            </div>
          </form>
        ) : null}
      </Panel>

      {profile ? (
        <Panel title="当前生效概览" description="方便你快速确认当前线上配置，不用自己再换算。">
          <div className="stack">
            <div className="card">
              <strong>语气</strong>
              <p>{profile.tone}</p>
            </div>
            <div className="card">
              <strong>客服人设</strong>
              <p>{profile.persona_notes || "未设置"}</p>
            </div>
            <div className="card">
              <strong>禁用词</strong>
              <p>{profile.banned_phrases_json?.join(" / ") || "未设置"}</p>
            </div>
            <div className="card">
              <strong>延迟与 typing</strong>
              <p>
                {profile.delay_min_ms}ms - {profile.delay_max_ms}ms / typing {profile.typing_enabled ? "开启" : "关闭"}
              </p>
            </div>
            <div className="card">
              <strong>澄清轮数</strong>
              <p>{profile.clarify_max_turns}</p>
            </div>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
