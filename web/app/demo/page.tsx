import type { Metadata } from "next";
import DemoClient from "./demo-client";

export const metadata: Metadata = {
  title: "Mailhub Demo",
  description: "使用公开示例数据体验 Mailhub 的 AI 邮箱业务视图。",
};

export default function MailhubDemoPage() {
  return <DemoClient />;
}
