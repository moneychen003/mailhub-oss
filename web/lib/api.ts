const BASE = "";  // 走相对 /api/* -> next rewrite -> FastAPI

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(BASE + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!r.ok) {
    let body: any = null;
    try { body = await r.json(); } catch {}
    const err: any = new Error(body?.detail || r.statusText);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  if (r.status === 204) return null;
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r.text();
}

export const api = {
  get: (p: string) => req(p),
  post: (p: string, body?: any) => req(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: (p: string, body?: any) => req(p, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: (p: string, body?: any) => req(p, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: (p: string) => req(p, { method: "DELETE" }),
};

export const fetcher = (url: string) => api.get(url);

export function priorityColor(p?: string | null) {
  return {
    urgent: "bg-red-100 text-red-700 border-red-200",
    high: "bg-orange-100 text-orange-700 border-orange-200",
    normal: "bg-sky-100 text-sky-700 border-sky-200",
    low: "bg-slate-100 text-slate-600 border-slate-200",
    spam: "bg-neutral-100 text-neutral-500 border-neutral-200",
  }[p || "normal"] || "bg-slate-100 text-slate-600 border-slate-200";
}

export function priorityLabel(p?: string | null) {
  return { urgent: "🚨 紧急", high: "❗ 高", normal: "📨 普通", low: "💬 低", spam: "🗑 垃圾" }[p || "normal"] || "📨";
}

export function timeAgo(ts?: string | null) {
  if (!ts) return "";
  const d = new Date(ts);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s/60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s/3600)} 小时前`;
  if (s < 86400*7) return `${Math.floor(s/86400)} 天前`;
  return d.toLocaleDateString("zh-CN");
}
