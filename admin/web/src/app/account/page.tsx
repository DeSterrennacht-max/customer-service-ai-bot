"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { CurrentUser } from "@/types/api";

export default function AccountPage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;

    async function loadMe() {
      try {
        const currentUser = await api.me();
        if (cancelled) {
          return;
        }
        setMe(currentUser);
        setError(null);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "账号信息加载失败");
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadMe();
    return () => {
      cancelled = true;
    };
  }, [router]);

  function resetForm() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setError(null);

    if (!currentPassword.trim()) {
      setError("请输入当前密码。");
      return;
    }
    if (!newPassword.trim()) {
      setError("请输入新密码。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }

    startTransition(async () => {
      try {
        await api.changePassword({
          current_password: currentPassword,
          new_password: newPassword
        });
        setMessage("密码已更新。下次登录请使用新密码。");
        resetForm();
      } catch (submitError) {
        if (submitError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setError(submitError instanceof Error ? submitError.message : "修改密码失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel title="账号设置" description="你可以在这里查看当前租户名、当前登录用户名，并自助修改密码。用户名不可自助修改，如需调整请联系超级管理员。">
        {isLoading ? <p className="muted">加载中...</p> : null}
        {error && !me ? <p className="error-text">{error}</p> : null}
        {me ? (
          <div className="grid">
            <div className="card">
              <strong>当前租户名</strong>
              <p>{me.tenant_name || "平台账号"}</p>
            </div>
            <div className="card">
              <strong>当前登录用户名</strong>
              <p className="mono-text">{me.login_username}</p>
            </div>
          </div>
        ) : null}
      </Panel>

      <Panel title="修改密码" description="请输入当前密码，再设置新的登录密码。系统不会允许你在这里修改用户名。">
        <form className="stack" onSubmit={handleSubmit}>
          <label>
            当前密码
            <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
          </label>
          <label>
            新密码
            <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
          </label>
          <label>
            再输入一次新密码
            <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
          </label>
          {message ? <p className="success-text">{message}</p> : null}
          {error && me ? <p className="error-text">{error}</p> : null}
          <div className="button-row">
            <button type="submit" disabled={isPending}>
              {isPending ? "保存中..." : "修改密码"}
            </button>
            <button type="button" className="button-secondary" onClick={resetForm} disabled={isPending}>
              清空
            </button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
