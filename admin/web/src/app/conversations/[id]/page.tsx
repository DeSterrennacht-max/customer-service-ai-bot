"use client";

import { useEffect, useState, useTransition } from "react";
import { useParams, useRouter } from "next/navigation";

import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { ConversationDetail } from "@/types/api";

export default function ConversationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const conversationId = params.id;
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;

    async function loadConversation() {
      try {
        const data = await api.conversation(conversationId);
        if (cancelled) {
          return;
        }
        setConversation(data);
        setError(null);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "会话加载失败");
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadConversation();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void loadConversation(); }, 10000);
    return () => {
      window.clearInterval(timer);
      cancelled = true;
    };
  }, [conversationId, router]);

  function handleConversationAction(action: "takeover" | "release") {
    if (!conversation) {
      return;
    }

    setActionError(null);
    startTransition(async () => {
      try {
        if (action === "takeover") {
          await api.takeoverConversation(conversation.id);
        } else {
          await api.releaseConversation(conversation.id);
        }
        const refreshed = await api.conversation(conversation.id);
        setConversation(refreshed);
      } catch (actionFailure) {
        if (actionFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setActionError(actionFailure instanceof Error ? actionFailure.message : "操作失败");
      }
    });
  }

  function retryMessage(messageId: string, uncertain: boolean) {
    if (uncertain && !window.confirm("发送结果尚未确认，请先在 Telegram 核实。确定重新发送尚未确认的部分吗？这可能造成重复消息。")) return;
    setActionError(null);
    startTransition(async () => {
      try {
        await api.retryMessage(conversationId, messageId, uncertain);
        setConversation(await api.conversation(conversationId));
      } catch (error) {
        setActionError(error instanceof Error ? error.message : "补发失败");
      }
    });
  }

  const deliveryLabels: Record<string, string> = { pending: "等待发送", queued: "等待发送", preparing: "正在准备", sending: "正在发送", sent: "已发送", failed: "发送失败", partial: "部分发送成功", uncertain: "结果待确认", cancelled: "已取消" };

  return (
    <div className="grid">
      <Panel
        title="会话详情"
        description={conversation ? `客户 ${conversation.customer_display_name ?? conversation.telegram_user_id}` : "加载会话中"}
      >
        {isLoading ? <p className="muted">加载中...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {conversation ? (
          <div className="stack">
            <div className="card">状态：{conversation.status}</div>
            {conversation.status === "handoff" ? (
              <p className="muted">转人工后默认由客服接管；若客户最后一条消息后 8 小时无新消息，系统会自动释放回机器人。</p>
            ) : null}
            <div className="card">Telegram Chat ID：{conversation.telegram_chat_id}</div>
            <div className="card">Handoff Ticket：{conversation.handoff_ticket_id ?? "无"}</div>
            <div className="button-row">
              <button
                type="button"
                onClick={() => handleConversationAction("takeover")}
                disabled={isPending || conversation.status === "handoff"}
              >
                {isPending && conversation.status !== "handoff" ? "处理中..." : "人工接管"}
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={() => handleConversationAction("release")}
                disabled={isPending || conversation.status !== "handoff"}
              >
                {isPending && conversation.status === "handoff" ? "处理中..." : "释放会话"}
              </button>
            </div>
            {actionError ? <p className="error-text">{actionError}</p> : null}
          </div>
        ) : null}
      </Panel>
      <Panel title="消息记录" description="按时间顺序查看客户、机器人、人工消息。">
        {conversation ? (
          <div className="conversation-thread">
            {conversation.messages.map((message) => (
              <div key={message.id} className="bubble" data-source={message.source}>
                <strong>{message.source}</strong>
                <p>{message.content_text}</p>
                {message.deliveries?.length ? <p className="muted">{deliveryLabels[message.delivery_status] ?? message.delivery_status}</p> : null}
                {message.deliveries?.map((delivery) => (
                  <small key={delivery.id} className="muted">{delivery.kind === "photo" ? "图片" : "文字"}：{deliveryLabels[delivery.status] ?? delivery.status}{delivery.last_error ? `（${delivery.last_error}）` : ""}</small>
                ))}
                {message.deliveries?.some((delivery) => ["failed", "uncertain"].includes(delivery.status)) ? (
                  <button type="button" className="button-secondary" disabled={isPending}
                    onClick={() => retryMessage(message.id, message.deliveries.some((delivery) => delivery.status === "uncertain"))}>
                    重新发送未成功部分
                  </button>
                ) : null}
                <small className="muted">
                  {message.intent ?? "no-intent"} / {message.risk_level} / {message.created_at}
                </small>
              </div>
            ))}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
