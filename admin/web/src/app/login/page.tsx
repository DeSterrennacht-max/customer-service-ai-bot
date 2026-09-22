"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [passwordChanged, setPasswordChanged] = useState(false);
  useEffect(() => { setPasswordChanged(new URLSearchParams(window.location.search).has("passwordChanged")); }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    startTransition(async () => {
      try {
        await login(username, password);
        router.replace("/");
        router.refresh();
      } catch (submitError) {
        setError(submitError instanceof Error ? submitError.message : "登录失败");
      }
    });
  }

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="badge">Admin Login</div>
        <h1>登录后台</h1>
        <p className="muted">请输入你的用户名和密码。</p>
        {passwordChanged ? <p className="success-text">密码已更新，请使用新密码重新登录。</p> : null}
        <form className="stack" onSubmit={handleSubmit}>
          <label>
            用户名
            <input type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            密码
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
          <button type="submit" disabled={isPending}>
            {isPending ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
