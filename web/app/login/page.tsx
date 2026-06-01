"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      await api.post("/api/auth/login", { username: u, password: p });
      router.push("/");
    } catch (e: any) {
      setErr(e.message || "登录失败");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-100 to-blue-100">
      <form onSubmit={submit} className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm space-y-4">
        <div className="text-center">
          <div className="text-3xl mb-1">📬</div>
          <div className="text-xl font-semibold text-slate-800">mailhub</div>
          <div className="text-xs text-slate-500 mt-1">邮件管理 · 提醒中心</div>
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">用户名</label>
          <input className="w-full border rounded px-3 py-2 text-sm" value={u} onChange={e=>setU(e.target.value)} autoFocus required />
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">密码</label>
          <input type="password" className="w-full border rounded px-3 py-2 text-sm" value={p} onChange={e=>setP(e.target.value)} required />
        </div>
        {err && <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{err}</div>}
        <button type="submit" disabled={loading} className="w-full bg-sky-600 text-white rounded py-2 text-sm font-medium hover:bg-sky-700 disabled:opacity-50">
          {loading ? "登录中..." : "登录"}
        </button>
      </form>
    </div>
  );
}
