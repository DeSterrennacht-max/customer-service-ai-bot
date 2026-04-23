"use client";

import { FormEvent, useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Panel } from "@/components/panel";
import { AuthError } from "@/lib/auth";
import { api } from "@/lib/api";
import { CurrentUser, TenantCreatePayload, TenantSummary, TenantUpdatePayload } from "@/types/api";

interface TenantFormState {
  name: string;
  login_username: string;
  status: string;
  valid_from: string;
  valid_until: string;
}

const DEFAULT_TENANT_FORM: TenantFormState = {
  name: "",
  login_username: "",
  status: "active",
  valid_from: "",
  valid_until: ""
};

function toDateTimeLocal(value?: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toApiDateTime(value: string): string | null {
  if (!value.trim()) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

function getTenantRuntimeLabel(tenant: TenantSummary): string {
  if (tenant.status !== "active") {
    return "停用";
  }
  const now = Date.now();
  if (tenant.valid_from && new Date(tenant.valid_from).getTime() > now) {
    return "未生效";
  }
  if (tenant.valid_until && new Date(tenant.valid_until).getTime() < now) {
    return "已过期";
  }
  return "运行中";
}

export default function TenantsPage() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [editingTenantId, setEditingTenantId] = useState<string | null>(null);
  const [tenantForm, setTenantForm] = useState<TenantFormState>(DEFAULT_TENANT_FORM);
  const [tenantSubmitMessage, setTenantSubmitMessage] = useState<string | null>(null);
  const [tenantSubmitError, setTenantSubmitError] = useState<string | null>(null);
  const [tenantTemporaryPassword, setTenantTemporaryPassword] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;

    async function loadContext() {
      try {
        const [currentUser, tenantData] = await Promise.all([api.me(), api.tenants()]);
        if (cancelled) {
          return;
        }
        if (currentUser.role !== "super_admin") {
          router.replace("/");
          return;
        }
        setMe(currentUser);
        setTenants(tenantData);
        setTenantSubmitError(null);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (loadError instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setTenantSubmitError(loadError instanceof Error ? loadError.message : "租户管理加载失败");
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadContext();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function reloadTenants() {
    const tenantData = await api.tenants();
    setTenants(tenantData);
    return tenantData;
  }

  function startEditTenant(tenant: TenantSummary) {
    setEditingTenantId(tenant.id);
    setTenantForm({
      name: tenant.name,
      login_username: tenant.admin_login_username ?? "",
      status: tenant.status,
      valid_from: toDateTimeLocal(tenant.valid_from),
      valid_until: toDateTimeLocal(tenant.valid_until)
    });
    setTenantSubmitError(null);
    setTenantSubmitMessage(null);
    setTenantTemporaryPassword(null);
  }

  function cancelEditTenant() {
    setEditingTenantId(null);
    setTenantForm(DEFAULT_TENANT_FORM);
    setTenantSubmitError(null);
    setTenantSubmitMessage(null);
    setTenantTemporaryPassword(null);
  }

  function updateTenantForm<K extends keyof TenantFormState>(key: K, value: TenantFormState[K]) {
    setTenantForm((current) => ({ ...current, [key]: value }));
  }

  function handleTenantSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTenantSubmitError(null);
    setTenantSubmitMessage(null);
    setTenantTemporaryPassword(null);

    if (!tenantForm.name.trim()) {
      setTenantSubmitError("租户名称不能为空。");
      return;
    }
    if (!tenantForm.login_username.trim()) {
      setTenantSubmitError("管理员登录用户名不能为空。");
      return;
    }

    startTransition(async () => {
      try {
        const payload = {
          name: tenantForm.name.trim(),
          login_username: tenantForm.login_username.trim(),
          status: tenantForm.status,
          valid_from: toApiDateTime(tenantForm.valid_from),
          valid_until: toApiDateTime(tenantForm.valid_until)
        };

        if (editingTenantId) {
          await api.updateTenant(editingTenantId, payload as TenantUpdatePayload);
          setTenantSubmitMessage("租户配置已更新。");
        } else {
          const response = await api.createTenant(payload as TenantCreatePayload);
          setTenantSubmitMessage("租户已创建。请立刻复制下面的临时密码发给客户管理员。");
          setTenantTemporaryPassword(response.temporary_password);
        }

        await reloadTenants();
        setEditingTenantId(null);
        setTenantForm(DEFAULT_TENANT_FORM);
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setTenantSubmitError(submitFailure instanceof Error ? submitFailure.message : "租户配置保存失败");
      }
    });
  }

  function handleResetTenantAdminPassword(tenant: TenantSummary) {
    setTenantSubmitError(null);
    setTenantSubmitMessage(null);
    setTenantTemporaryPassword(null);

    startTransition(async () => {
      try {
        const response = await api.resetTenantAdminPassword(tenant.id);
        setTenantSubmitMessage(`已为 ${tenant.name} 重新生成管理员临时密码。请立即复制给客户管理员。`);
        setTenantTemporaryPassword(response.temporary_password);
      } catch (submitFailure) {
        if (submitFailure instanceof AuthError) {
          router.replace("/login");
          return;
        }
        setTenantSubmitError(submitFailure instanceof Error ? submitFailure.message : "重置密码失败");
      }
    });
  }

  return (
    <div className="grid">
      <Panel title="租户管理" description="这里只有超级管理员可见。你可以在这里创建租户、修改租户名称和管理员登录用户名，并设置租户生效时间与到期时间。">
        {isLoading ? <p className="muted">加载中...</p> : null}
        {tenantSubmitError && !me ? <p className="error-text">{tenantSubmitError}</p> : null}
        {me ? (
          <div className="grid">
            <table>
              <thead>
                <tr>
                  <th>租户名称</th>
                  <th>管理员登录用户名</th>
                  <th>运行状态</th>
                  <th>状态</th>
                  <th>生效时间</th>
                  <th>到期时间</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr key={tenant.id}>
                    <td>
                      <strong>{tenant.name}</strong>
                      <div className="table-subtext">ID: {tenant.id}</div>
                    </td>
                    <td>{tenant.admin_login_username ?? "未创建"}</td>
                    <td>{getTenantRuntimeLabel(tenant)}</td>
                    <td>{tenant.status}</td>
                    <td>{tenant.valid_from ? new Date(tenant.valid_from).toLocaleString("zh-CN") : "不限"}</td>
                    <td>{tenant.valid_until ? new Date(tenant.valid_until).toLocaleString("zh-CN") : "不限"}</td>
                    <td>{new Date(tenant.created_at).toLocaleString("zh-CN")}</td>
                    <td>
                      <button type="button" className="button-secondary" onClick={() => startEditTenant(tenant)}>
                        编辑
                      </button>
                      <button type="button" className="button-secondary" onClick={() => handleResetTenantAdminPassword(tenant)}>
                        重置密码
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <form className="card stack" onSubmit={handleTenantSubmit}>
              <strong>{editingTenantId ? "编辑租户" : "新建租户"}</strong>
              <label>
                租户名称
                <input type="text" value={tenantForm.name} onChange={(event) => updateTenantForm("name", event.target.value)} />
              </label>
              <label>
                管理员登录用户名
                <input
                  type="text"
                  value={tenantForm.login_username}
                  onChange={(event) => updateTenantForm("login_username", event.target.value)}
                  placeholder="例如：tenant_alpha"
                />
              </label>
              <label>
                状态
                <select value={tenantForm.status} onChange={(event) => updateTenantForm("status", event.target.value)}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
              <div className="grid faq-form-grid">
                <label>
                  生效时间
                  <input type="datetime-local" value={tenantForm.valid_from} onChange={(event) => updateTenantForm("valid_from", event.target.value)} />
                </label>
                <label>
                  到期时间
                  <input type="datetime-local" value={tenantForm.valid_until} onChange={(event) => updateTenantForm("valid_until", event.target.value)} />
                </label>
              </div>
              <div className="card">
                <strong>说明</strong>
                <p>租户状态为 inactive、未到生效时间或已超过到期时间时，这个租户名下的机器人与后台管理员都会停止工作。</p>
                <p>每个租户固定只有一个后台管理员账号，使用“管理员登录用户名 + 密码”登录后台。</p>
              </div>
              {tenantSubmitMessage ? <p className="success-text">{tenantSubmitMessage}</p> : null}
              {tenantTemporaryPassword ? (
                <div className="card">
                  <strong>管理员临时密码</strong>
                  <p className="mono-text">{tenantTemporaryPassword}</p>
                  <p>这个密码只会在创建或重置后显示一次，请立即复制保存。</p>
                </div>
              ) : null}
              {tenantSubmitError && me ? <p className="error-text">{tenantSubmitError}</p> : null}
              <div className="button-row">
                <button type="submit" disabled={isPending}>
                  {isPending ? "保存中..." : editingTenantId ? "保存租户配置" : "创建租户"}
                </button>
                {editingTenantId ? (
                  <button type="button" className="button-secondary" onClick={cancelEditTenant} disabled={isPending}>
                    取消
                  </button>
                ) : null}
              </div>
            </form>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
