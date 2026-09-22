"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { logout, isAuthenticated } from "@/lib/auth";

const links = [
  { href: "/", label: "概览" },
  { href: "/conversations", label: "会话" },
  { href: "/bot-profiles", label: "机器人配置" },
  { href: "/faqs", label: "FAQ" },
  { href: "/knowledge-pages", label: "知识页" },
  { href: "/style-profile", label: "风格配置" },
  { href: "/account", label: "账号设置" }
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authenticated, setAuthenticated] = useState(false);
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  useEffect(() => {
    setAuthenticated(isAuthenticated());
  }, [pathname]);

  useEffect(() => {
    let cancelled = false;

    async function loadMe() {
      if (!isAuthenticated()) {
        if (!cancelled) {
          setIsSuperAdmin(false);
        }
        return;
      }

      try {
        const me = await api.me();
        if (!cancelled) {
          setIsSuperAdmin(me.role === "super_admin");
        }
      } catch {
        if (!cancelled) {
          setIsSuperAdmin(false);
        }
      }
    }

    void loadMe();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  async function handleLogout() {
    try {
      await logout();
      setAuthenticated(false);
      setIsSuperAdmin(false);
      router.replace("/login");
    } catch {
      setLogoutError("退出登录失败，请重试。");
    }
  }

  const visibleLinks = isSuperAdmin ? [...links.slice(0, 3), { href: "/tenants", label: "租户管理" }, ...links.slice(3)] : links;

  return (
    <nav className="sidebar">
      <div className="brand">
        <span className="brand-dot" />
        <div>
          <strong>Customer Service Bot</strong>
          <p>Telegram Admin</p>
        </div>
      </div>
      <div className="nav-links">
        {visibleLinks.map((link) => (
          <Link key={link.href} href={link.href} className={`nav-link${pathname === link.href ? " nav-link-active" : ""}`}>
            {link.label}
          </Link>
        ))}
      </div>
      <div className="nav-footer">
        {logoutError ? <p className="error-text">{logoutError}</p> : null}
        {authenticated ? (
          <button type="button" className="button-secondary nav-button" onClick={handleLogout}>
            退出登录
          </button>
        ) : (
          <Link href="/login" className={`nav-link${pathname === "/login" ? " nav-link-active" : ""}`}>
            登录
          </Link>
        )}
      </div>
    </nav>
  );
}
