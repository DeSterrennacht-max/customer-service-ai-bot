"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { Conversation } from "@/types/api";

export default function ConversationsPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadConversations() {
      try {
        const data = await api.conversations();
        if (cancelled) {
          return;
        }
        setConversations(data);
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

    void loadConversations();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <Panel title="会话列表" description="展示 Telegram 私聊会话与当前人工接管状态。">
      {isLoading ? <p className="muted">加载中...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {!isLoading && !error ? (
        <table>
          <thead>
            <tr>
              <th>客户</th>
              <th>状态</th>
              <th>Telegram Chat</th>
              <th>最近消息</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {conversations.map((conversation) => (
              <tr key={conversation.id}>
                <td>{conversation.customer_display_name ?? conversation.telegram_user_id}</td>
                <td>
                  <span className={conversation.status === "handoff" ? "badge badge-danger" : "badge"}>
                    {conversation.status}
                  </span>
                </td>
                <td>{conversation.telegram_chat_id}</td>
                <td>{conversation.last_message_at ?? "暂无"}</td>
                <td>
                  <Link href={`/conversations/${conversation.id}`}>查看详情</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </Panel>
  );
}
