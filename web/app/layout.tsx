import "./globals.css";
import { ReactNode } from "react";
import ClientRuntimeGuard from "./runtime-guard";

export const metadata = { title: "mailhub", description: "邮件管理 + 提醒" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-Hans">
      <body>
        <ClientRuntimeGuard />
        {children}
      </body>
    </html>
  );
}
