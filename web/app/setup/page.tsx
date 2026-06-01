"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";

export default function SetupPage() {
  const router = useRouter();
  const { data, mutate } = useSWR("/api/setup/status", fetcher);
  const [form, setForm] = useState({
    username: "admin",
    password: "",
    email: "",
    display_name: "",
    public_base_url: "",
    inbound_host: "",
  });
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (data?.app) {
      setForm((f) => ({
        ...f,
        public_base_url: f.public_base_url || data.app.public_base_url || "http://localhost:3024",
        inbound_host: f.inbound_host || data.app.inbound_host || "",
      }));
    }
  }, [data]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api.post("/api/setup/admin", form);
      await mutate();
      setMsg("初始化完成，可以登录了。");
      setTimeout(() => router.push("/login"), 700);
    } catch (e: any) {
      setMsg(e.message || "初始化失败");
    }
  }

  if (data && !data.needs_setup) {
    return (
      <main className="min-h-screen bg-slate-50 p-6">
        <div className="mx-auto max-w-lg rounded-lg bg-white p-6 shadow-sm">
          <h1 className="text-xl font-semibold">Mailhub 已初始化</h1>
          <button onClick={() => router.push("/login")} className="btn-primary mt-4">去登录</button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <form onSubmit={submit} className="mx-auto max-w-2xl space-y-4 rounded-lg bg-white p-6 shadow-sm">
        <div>
          <h1 className="text-xl font-semibold">初始化 Mailhub</h1>
          <p className="mt-1 text-sm text-slate-500">创建第一个管理员后，其他配置都可以在设置页完成。</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="管理员用户名"><input className="input" value={form.username} onChange={e=>setForm({...form, username: e.target.value})} required /></Field>
          <Field label="管理员密码"><input className="input" type="password" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} minLength={10} required /></Field>
          <Field label="管理员邮箱"><input className="input" type="email" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} required /></Field>
          <Field label="显示名"><input className="input" value={form.display_name} onChange={e=>setForm({...form, display_name: e.target.value})} /></Field>
          <Field label="公开访问 URL"><input className="input" value={form.public_base_url} onChange={e=>setForm({...form, public_base_url: e.target.value})} required /></Field>
          <Field label="收信主机名"><input className="input" value={form.inbound_host} onChange={e=>setForm({...form, inbound_host: e.target.value})} /></Field>
        </div>
        {msg && <div className="rounded bg-slate-100 px-3 py-2 text-sm">{msg}</div>}
        <button className="btn-primary" type="submit">完成初始化</button>
      </form>
    </main>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return (
    <label className="block text-sm">
      <div className="mb-1 text-xs text-slate-600">{label}</div>
      {children}
    </label>
  );
}
