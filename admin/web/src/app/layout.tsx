import type { Metadata } from "next";

import { Nav } from "@/components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Customer Service Bot Admin",
  description: "Telegram customer service bot dashboard"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-shell">
          <Nav />
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
