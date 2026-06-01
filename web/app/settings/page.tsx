"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";

type SettingsTab =
  | "setup"
  | "app"
  | "domains"
  | "smtp"
  | "imap"
  | "ai"
  | "tg"
  | "senders"
  | "rules"
  | "templates"
  | "users"
  | "diagnostics";

const TABS: [SettingsTab, string][] = [
  ["setup", "安装"],
  ["app", "站点"],
  ["domains", "域名"],
  ["smtp", "发信"],
  ["imap", "收信"],
  ["ai", "AI"],
  ["tg", "Telegram"],
  ["senders", "发件人"],
  ["rules", "规则"],
  ["templates", "模板"],
  ["users", "用户"],
  ["diagnostics", "诊断"],
];

export default function Settings() {
  const [tab, setTab] = useState<SettingsTab>("setup");
  const { data: me } = useSWR("/api/auth/me", fetcher);
  const isAdmin = me?.role === "admin";

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-6xl p-6">
        <div className="mb-4 flex items-center gap-3">
          <Link href="/" className="text-sm text-slate-500 hover:text-slate-800">返回收件箱</Link>
          <h1 className="text-xl font-semibold">设置</h1>
        </div>
        <div className="flex flex-wrap gap-1 border-b bg-white rounded-t-lg overflow-hidden">
          {TABS.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-3 py-2 text-sm ${tab === k ? "bg-sky-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="bg-white p-6 rounded-b-lg shadow-sm">
          {!isAdmin && tab !== "setup" ? (
            <div className="text-sm text-slate-500">需要管理员权限。</div>
          ) : (
            <>
              {tab === "setup" && <SetupPanel />}
              {tab === "app" && <AppPanel />}
              {tab === "domains" && <DomainsPanel />}
              {tab === "smtp" && <SMTPPanel />}
              {tab === "imap" && <IMAPPanel />}
              {tab === "ai" && <AIPanel />}
              {tab === "tg" && <TGPanel />}
              {tab === "senders" && <SendersPanel />}
              {tab === "rules" && <RulesPanel />}
              {tab === "templates" && <TemplatesPanel />}
              {tab === "users" && <UsersPanel />}
              {tab === "diagnostics" && <DiagnosticsPanel />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SetupPanel() {
  const { data } = useSWR("/api/setup/status", fetcher);
  return (
    <div className="space-y-4">
      <StatusGrid
        items={[
          ["初始化", data?.needs_setup ? "需要创建管理员" : "已创建管理员", !data?.needs_setup],
          ["JWT", data?.jwt_configured ? "已配置" : "未配置", !!data?.jwt_configured],
          ["用户数", String(data?.users_count ?? "-"), (data?.users_count ?? 0) > 0],
        ]}
      />
      <div className="grid gap-3 md:grid-cols-3">
        {data?.paths?.map((p: any) => (
          <div key={p.name} className="rounded border p-3 text-sm">
            <div className="font-medium">{p.name}</div>
            <div className="mt-1 break-all text-xs text-slate-500">{p.path}</div>
            <Badge ok={p.exists && p.writable}>{p.exists && p.writable ? "可写" : "需检查"}</Badge>
          </div>
        ))}
      </div>
      {data?.needs_setup && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          当前没有管理员。打开 <Link className="underline" href="/setup">/setup</Link> 完成首次初始化。
        </div>
      )}
    </div>
  );
}

function AppPanel() {
  const { data, mutate } = useSWR("/api/config/app", fetcher);
  const [form, setForm] = useState<any>({ app_name: "Mailhub", public_base_url: "", inbound_host: "", default_timezone: "UTC" });
  const [msg, setMsg] = useState("");
  useEffect(() => { if (data) setForm(data); }, [data]);

  async function save() {
    setMsg("");
    try {
      await api.put("/api/config/app", form);
      await mutate();
      setMsg("已保存");
    } catch (e: any) { setMsg(e.message); }
  }

  return (
    <Panel>
      <Field label="应用名称"><input className="input" value={form.app_name || ""} onChange={e=>setForm({...form, app_name: e.target.value})} /></Field>
      <Field label="公开访问 URL"><input className="input" value={form.public_base_url || ""} onChange={e=>setForm({...form, public_base_url: e.target.value})} placeholder="https://mail.example.com" /></Field>
      <Field label="收信主机名"><input className="input" value={form.inbound_host || ""} onChange={e=>setForm({...form, inbound_host: e.target.value})} placeholder="mail.example.com" /></Field>
      <Field label="默认时区"><input className="input" value={form.default_timezone || ""} onChange={e=>setForm({...form, default_timezone: e.target.value})} placeholder="Asia/Shanghai" /></Field>
      <ActionRow msg={msg}><button onClick={save} className="btn-primary">保存</button></ActionRow>
    </Panel>
  );
}

function DomainsPanel() {
  const { data, mutate } = useSWR("/api/senders/domains", fetcher);
  const [form, setForm] = useState<any>({ domain: "", dkim_selector: "default", inbound_host: "", dkim_public_key: "", receive_enabled: true, send_enabled: true, notes: "" });
  const [dns, setDns] = useState<any>(null);
  const [msg, setMsg] = useState("");

  async function add() {
    setMsg("");
    try {
      await api.post("/api/senders/domains", form);
      setForm({ domain: "", dkim_selector: "default", inbound_host: "", dkim_public_key: "", receive_enabled: true, send_enabled: true, notes: "" });
      await mutate();
    } catch (e: any) { setMsg(e.message); }
  }
  async function verify(id: number) {
    const r = await api.post(`/api/senders/domains/${id}/verify`);
    setMsg(r.ok ? "DNS 验证通过" : "DNS 仍有未通过项");
    await mutate();
  }
  async function loadDns(id: number) {
    setDns(await api.get(`/api/senders/domains/${id}/dns`));
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.map((d: any) => (
          <div key={d.id} className="rounded border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex-1 font-medium">{d.domain}</div>
              <Badge ok={d.mx_status === "active"}>MX {d.mx_status || "pending"}</Badge>
              <Badge ok={d.spf_status === "active"}>SPF {d.spf_status || "pending"}</Badge>
              <Badge ok={d.dkim_status === "active"}>DKIM {d.dkim_status || "pending"}</Badge>
              <Badge ok={d.dmarc_status === "active"}>DMARC {d.dmarc_status || "pending"}</Badge>
              <button onClick={()=>loadDns(d.id)} className="btn-secondary">DNS</button>
              <button onClick={()=>verify(d.id)} className="btn-secondary">验证</button>
            </div>
            <div className="mt-1 text-xs text-slate-500">{d.receive_enabled ? "收信开启" : "收信关闭"} · {d.send_enabled ? "发信开启" : "发信关闭"} · {d.inbound_host || "未设置收信主机"}</div>
          </div>
        ))}
      </div>
      {dns && (
        <div className="rounded border bg-slate-50 p-3 text-sm">
          {Object.entries(dns).map(([k, r]: any) => (
            <div key={k} className="grid gap-2 border-b py-2 last:border-b-0 md:grid-cols-[100px_80px_1fr]">
              <div className="font-medium">{r.name}</div>
              <div>{r.type}</div>
              <code className="break-all text-xs">{r.value}</code>
            </div>
          ))}
        </div>
      )}
      <Panel title="新增域名">
        <Field label="域名"><input className="input" value={form.domain} onChange={e=>setForm({...form, domain: e.target.value})} placeholder="example.com" /></Field>
        <Field label="DKIM selector"><input className="input" value={form.dkim_selector} onChange={e=>setForm({...form, dkim_selector: e.target.value})} /></Field>
        <Field label="收信主机"><input className="input" value={form.inbound_host} onChange={e=>setForm({...form, inbound_host: e.target.value})} placeholder="mail.example.com" /></Field>
        <Field label="DKIM public key"><textarea className="input min-h-20" value={form.dkim_public_key} onChange={e=>setForm({...form, dkim_public_key: e.target.value})} /></Field>
        <label className="check"><input type="checkbox" checked={form.receive_enabled} onChange={e=>setForm({...form, receive_enabled: e.target.checked})} /> 启用收信</label>
        <label className="check"><input type="checkbox" checked={form.send_enabled} onChange={e=>setForm({...form, send_enabled: e.target.checked})} /> 启用发信</label>
        <ActionRow msg={msg}><button onClick={add} className="btn-primary">添加域名</button></ActionRow>
      </Panel>
    </div>
  );
}

function SMTPPanel() {
  const { data, mutate } = useSWR("/api/config/smtp", fetcher);
  const [form, setForm] = useState<any>({ mode: "local_postfix", host: "", port: 587, username: "", password: "", use_tls: false, use_starttls: true, enabled: true });
  const [msg, setMsg] = useState("");
  useEffect(() => { if (data) setForm({ ...data, password: "" }); }, [data]);
  async function save() {
    setMsg("");
    try { await api.put("/api/config/smtp", form); await mutate(); setMsg("已保存"); } catch (e: any) { setMsg(e.message); }
  }
  async function test() {
    const r = await api.post("/api/config/smtp/test");
    setMsg(`${r.ok ? "通过" : "失败"}：${r.message}`);
  }
  return (
    <Panel>
      <Field label="发信模式">
        <select className="input" value={form.mode} onChange={e=>setForm({...form, mode: e.target.value})}>
          <option value="smtp">远端 SMTP</option>
          <option value="local_postfix">本机 Postfix</option>
        </select>
      </Field>
      <Field label="SMTP host"><input className="input" value={form.host || ""} onChange={e=>setForm({...form, host: e.target.value})} /></Field>
      <Field label="端口"><input className="input" type="number" value={form.port || 587} onChange={e=>setForm({...form, port: Number(e.target.value)})} /></Field>
      <Field label="用户名"><input className="input" value={form.username || ""} onChange={e=>setForm({...form, username: e.target.value})} /></Field>
      <Field label="密码 / 应用专用密码"><input className="input" type="password" value={form.password || ""} onChange={e=>setForm({...form, password: e.target.value})} placeholder={data?.password_masked || ""} /></Field>
      <label className="check"><input type="checkbox" checked={!!form.use_starttls} onChange={e=>setForm({...form, use_starttls: e.target.checked})} /> STARTTLS</label>
      <label className="check"><input type="checkbox" checked={!!form.use_tls} onChange={e=>setForm({...form, use_tls: e.target.checked})} /> SSL/TLS</label>
      <label className="check"><input type="checkbox" checked={!!form.enabled} onChange={e=>setForm({...form, enabled: e.target.checked})} /> 启用发信</label>
      <ActionRow msg={msg}>
        <button onClick={save} className="btn-primary">保存</button>
        <button onClick={test} className="btn-secondary">测试</button>
      </ActionRow>
    </Panel>
  );
}

function IMAPPanel() {
  const { data, mutate } = useSWR("/api/config/imap", fetcher);
  const empty = { label: "", host: "", port: 993, username: "", password: "", mailbox: "INBOX", use_ssl: true, enabled: true, source: "" };
  const [form, setForm] = useState<any>(empty);
  const [msg, setMsg] = useState("");
  async function add() {
    setMsg("");
    try { await api.post("/api/config/imap", form); setForm(empty); await mutate(); } catch (e: any) { setMsg(e.message); }
  }
  async function test(id: number) {
    const r = await api.post(`/api/config/imap/${id}/test`);
    setMsg(`${r.ok ? "通过" : "失败"}：${r.message}`);
  }
  async function sync(id: number) {
    const r = await api.post(`/api/config/imap/${id}/sync`);
    setMsg(r.ok ? "同步完成" : `同步失败：${r.stderr || r.stdout}`);
    await mutate();
  }
  async function del(id: number) {
    if (!confirm("删除这个 IMAP 来源?")) return;
    await api.del(`/api/config/imap/${id}`);
    await mutate();
  }
  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.map((a: any) => (
          <div key={a.id} className="rounded border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex-1 font-medium">{a.label} <span className="text-slate-400">{a.username}</span></div>
              <Badge ok={a.enabled}>{a.enabled ? "启用" : "停用"}</Badge>
              <button onClick={()=>test(a.id)} className="btn-secondary">测试</button>
              <button onClick={()=>sync(a.id)} className="btn-secondary">同步一次</button>
              <button onClick={()=>del(a.id)} className="btn-danger">删除</button>
            </div>
            <div className="mt-1 text-xs text-slate-500">{a.host}:{a.port} · {a.mailbox} · UID {a.last_uid || "-"} · {a.last_error || "无错误"}</div>
          </div>
        ))}
      </div>
      <Panel title="新增 IMAP 来源">
        <Field label="名称"><input className="input" value={form.label} onChange={e=>setForm({...form, label: e.target.value})} /></Field>
        <Field label="Host"><input className="input" value={form.host} onChange={e=>setForm({...form, host: e.target.value})} placeholder="imap.gmail.com" /></Field>
        <Field label="端口"><input className="input" type="number" value={form.port} onChange={e=>setForm({...form, port: Number(e.target.value)})} /></Field>
        <Field label="用户名"><input className="input" value={form.username} onChange={e=>setForm({...form, username: e.target.value})} /></Field>
        <Field label="密码 / 应用专用密码"><input className="input" type="password" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} /></Field>
        <Field label="Mailbox"><input className="input" value={form.mailbox} onChange={e=>setForm({...form, mailbox: e.target.value})} /></Field>
        <Field label="来源标签"><input className="input" value={form.source} onChange={e=>setForm({...form, source: e.target.value})} placeholder="gmail / qq / support" /></Field>
        <label className="check"><input type="checkbox" checked={form.use_ssl} onChange={e=>setForm({...form, use_ssl: e.target.checked})} /> SSL</label>
        <label className="check"><input type="checkbox" checked={form.enabled} onChange={e=>setForm({...form, enabled: e.target.checked})} /> 启用</label>
        <ActionRow msg={msg}><button onClick={add} className="btn-primary">添加来源</button></ActionRow>
      </Panel>
      {msg && <div className="text-sm text-slate-600">{msg}</div>}
    </div>
  );
}

function AIPanel() {
  const { data, mutate } = useSWR("/api/config/ai", fetcher);
  const [form, setForm] = useState<any>({ provider: "openai", endpoint: "", api_key: "", model: "", system_prompt: "", enabled: true });
  const [msg, setMsg] = useState("");
  useEffect(() => { if (data) setForm({ ...data, api_key: "" }); }, [data]);
  async function save() {
    setMsg("");
    try { await api.put("/api/config/ai", form); await mutate(); setMsg("已保存"); } catch (e: any) { setMsg(e.message); }
  }
  return (
    <Panel>
      <Field label="Provider 协议"><select className="input" value={form.provider} onChange={e=>setForm({...form, provider: e.target.value})}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option></select></Field>
      <Field label="Endpoint"><input className="input" value={form.endpoint || ""} onChange={e=>setForm({...form, endpoint: e.target.value})} placeholder="https://api.openai.com/v1" /></Field>
      <Field label="API Key"><input className="input" type="password" value={form.api_key || ""} onChange={e=>setForm({...form, api_key: e.target.value})} placeholder={data?.api_key_masked || "留空不修改"} /></Field>
      <Field label="Model"><input className="input" value={form.model || ""} onChange={e=>setForm({...form, model: e.target.value})} /></Field>
      <Field label="System Prompt"><textarea className="input min-h-28 font-mono" value={form.system_prompt || ""} onChange={e=>setForm({...form, system_prompt: e.target.value})} /></Field>
      <label className="check"><input type="checkbox" checked={!!form.enabled} onChange={e=>setForm({...form, enabled: e.target.checked})} /> 启用 AI 分类</label>
      <ActionRow msg={msg}><button onClick={save} className="btn-primary">保存</button></ActionRow>
    </Panel>
  );
}

function TGPanel() {
  const { data, mutate } = useSWR("/api/config/tg", fetcher);
  const [form, setForm] = useState<any>({ bot_token: "", chat_id: "", push_min_priority: "high", enabled: false });
  const [msg, setMsg] = useState("");
  useEffect(() => { if (data) setForm({ ...data, bot_token: "" }); }, [data]);
  async function save() {
    setMsg("");
    try { await api.put("/api/config/tg", form); await mutate(); setMsg("已保存"); } catch (e: any) { setMsg(e.message); }
  }
  async function test() {
    const r = await api.post("/api/config/tg/test");
    setMsg(r.ok ? "推送已发出" : "推送未生效");
  }
  return (
    <Panel>
      <Field label="Bot Token"><input className="input" type="password" value={form.bot_token || ""} onChange={e=>setForm({...form, bot_token: e.target.value})} placeholder={data?.bot_token_masked || "留空不修改"} /></Field>
      <Field label="Chat ID"><input className="input" value={form.chat_id || ""} onChange={e=>setForm({...form, chat_id: e.target.value})} /></Field>
      <Field label="最低推送优先级"><select className="input" value={form.push_min_priority} onChange={e=>setForm({...form, push_min_priority: e.target.value})}><option value="urgent">urgent</option><option value="high">high</option><option value="normal">normal</option></select></Field>
      <label className="check"><input type="checkbox" checked={!!form.enabled} onChange={e=>setForm({...form, enabled: e.target.checked})} /> 启用 Telegram</label>
      <ActionRow msg={msg}><button onClick={save} className="btn-primary">保存</button><button onClick={test} className="btn-secondary">测试</button></ActionRow>
    </Panel>
  );
}

function SendersPanel() {
  const { data, mutate } = useSWR("/api/senders", fetcher);
  const { data: domains } = useSWR("/api/senders/domains", fetcher);
  const [form, setForm] = useState<any>({ email: "", display_name: "", signature_text: "", signature_html: "", is_default: false });
  const [msg, setMsg] = useState("");
  async function save() {
    setMsg("");
    try { await api.post("/api/senders", form); setForm({ email: "", display_name: "", signature_text: "", signature_html: "", is_default: false }); await mutate(); } catch (e: any) { setMsg(e.message); }
  }
  async function del(id: number) {
    if (!confirm("删除这个发件人?")) return;
    await api.del(`/api/senders/${id}`);
    await mutate();
  }
  async function makeDefault(s: any) {
    await api.post("/api/senders", { ...s, is_default: true });
    await mutate();
  }
  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.map((s: any) => (
          <div key={s.id} className="rounded border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex-1 font-medium">{s.display_name ? `${s.display_name} <${s.email}>` : s.email}</div>
              {s.is_default && <Badge ok>默认</Badge>}
              <button onClick={()=>makeDefault(s)} className="btn-secondary">设默认</button>
              <button onClick={()=>del(s.id)} className="btn-danger">删除</button>
            </div>
            <div className="mt-1 text-xs text-slate-500">{s.domain} · {s.signature_text || s.signature_html ? "已配置签名" : "无签名"}</div>
          </div>
        ))}
      </div>
      <Panel title="新增或更新发件人">
        <div className="text-xs text-slate-500">可用域名：{domains?.map((d: any) => d.domain).join(" / ") || "先添加域名"}</div>
        <Field label="Email"><input className="input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} placeholder="ops@example.com" /></Field>
        <Field label="显示名"><input className="input" value={form.display_name} onChange={e=>setForm({...form, display_name: e.target.value})} /></Field>
        <Field label="纯文本签名"><textarea className="input min-h-20" value={form.signature_text} onChange={e=>setForm({...form, signature_text: e.target.value})} /></Field>
        <Field label="HTML 签名"><textarea className="input min-h-20 font-mono" value={form.signature_html} onChange={e=>setForm({...form, signature_html: e.target.value})} /></Field>
        <label className="check"><input type="checkbox" checked={form.is_default} onChange={e=>setForm({...form, is_default: e.target.checked})} /> 设为默认</label>
        <ActionRow msg={msg}><button onClick={save} className="btn-primary">保存发件人</button></ActionRow>
      </Panel>
    </div>
  );
}

function RulesPanel() {
  const { data, mutate } = useSWR("/api/rules", fetcher);
  const [form, setForm] = useState({ scope: "from_domain", value: "", force_priority: "normal", active: true, apply_to_existing: false });
  const [msg, setMsg] = useState("");
  async function add() {
    setMsg("");
    try {
      const r = await api.post("/api/rules", form);
      setForm({ scope: "from_domain", value: "", force_priority: "normal", active: true, apply_to_existing: false });
      setMsg(r.affected_threads ? `已保存, 已应用到 ${r.affected_threads} 个会话` : "已保存");
      await mutate();
    } catch (e: any) {
      setMsg(e.message);
    }
  }
  async function toggle(r: any) {
    await api.patch(`/api/rules/${r.id}`, { active: !r.active });
    await mutate();
  }
  async function setPriority(r: any, p: string) {
    await api.patch(`/api/rules/${r.id}`, { force_priority: p });
    await mutate();
  }
  async function del(id: number) {
    if (!confirm("删除这个规则?")) return;
    await api.del(`/api/rules/${id}`);
    await mutate();
  }
  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.length ? data.map((r: any) => (
          <div key={r.id} className="flex flex-wrap items-center gap-2 rounded border p-3 text-sm">
            <Badge ok={r.active}>{r.active ? "启用" : "停用"}</Badge>
            <div className="flex-1"><span className="font-medium">{r.scope}</span> = <code>{r.value}</code></div>
            <select className="input w-36" value={r.force_priority} onChange={e=>setPriority(r, e.target.value)}>
              {["urgent","high","normal","low","spam"].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <button onClick={()=>toggle(r)} className="btn-secondary">{r.active ? "停用" : "启用"}</button>
            <button onClick={()=>del(r.id)} className="btn-danger">删除</button>
          </div>
        )) : <div className="text-sm text-slate-500">还没有规则。</div>}
      </div>
      <Panel title="新增规则">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="匹配范围">
            <select className="input" value={form.scope} onChange={e=>setForm({...form, scope: e.target.value})}>
              <option value="from_domain">发件人域名</option>
              <option value="from_email">发件人邮箱</option>
              <option value="subject_keyword">主题关键词</option>
            </select>
          </Field>
          <Field label="匹配值"><input className="input" value={form.value} onChange={e=>setForm({...form, value: e.target.value})} placeholder="example.com" /></Field>
          <Field label="强制优先级">
            <select className="input" value={form.force_priority} onChange={e=>setForm({...form, force_priority: e.target.value})}>
              {["urgent","high","normal","low","spam"].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
        </div>
        <label className="check"><input type="checkbox" checked={form.active} onChange={e=>setForm({...form, active: e.target.checked})} /> 启用</label>
        <label className="check"><input type="checkbox" checked={form.apply_to_existing} onChange={e=>setForm({...form, apply_to_existing: e.target.checked})} /> 应用到已有会话</label>
        <ActionRow msg={msg}><button onClick={add} className="btn-primary">保存规则</button></ActionRow>
      </Panel>
    </div>
  );
}

function TemplatesPanel() {
  const { data, mutate } = useSWR("/api/templates", fetcher);
  const [form, setForm] = useState({ name: "", content: "" });
  const [editing, setEditing] = useState<any>(null);
  const [msg, setMsg] = useState("");
  async function add() {
    setMsg("");
    try { await api.post("/api/templates", form); setForm({ name: "", content: "" }); await mutate(); } catch (e: any) { setMsg(e.message); }
  }
  async function saveEdit() {
    if (!editing?.id) return;
    setMsg("");
    try {
      await api.put(`/api/templates/${editing.id}`, { name: editing.name, content: editing.content });
      setEditing(null);
      await mutate();
      setMsg("已保存");
    } catch (e: any) {
      setMsg(e.message);
    }
  }
  async function del(id: number | null) {
    if (!id) return;
    await api.del(`/api/templates/${id}`);
    await mutate();
  }
  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.map((t: any, idx: number) => (
          <div key={t.id || `builtin-${idx}`} className="rounded border p-3 text-sm">
            <div className="flex items-center gap-2">
              <div className="flex-1 font-medium">{t.name}</div>
              {t.id ? (
                <>
                  <button onClick={()=>setEditing(t)} className="btn-secondary">编辑</button>
                  <button onClick={()=>del(t.id)} className="btn-danger">删除</button>
                </>
              ) : <Badge ok>内置</Badge>}
            </div>
            <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{t.content}</pre>
          </div>
        ))}
      </div>
      {editing && (
        <Panel title="编辑模板">
          <Field label="名称"><input className="input" value={editing.name} onChange={e=>setEditing({...editing, name: e.target.value})} /></Field>
          <Field label="HTML 内容"><textarea className="input min-h-24 font-mono" value={editing.content} onChange={e=>setEditing({...editing, content: e.target.value})} /></Field>
          <ActionRow msg={msg}>
            <button onClick={saveEdit} className="btn-primary">保存修改</button>
            <button onClick={()=>setEditing(null)} className="btn-secondary">取消</button>
          </ActionRow>
        </Panel>
      )}
      <Panel title="新增回复模板">
        <Field label="名称"><input className="input" value={form.name} onChange={e=>setForm({...form, name: e.target.value})} /></Field>
        <Field label="HTML 内容"><textarea className="input min-h-24 font-mono" value={form.content} onChange={e=>setForm({...form, content: e.target.value})} /></Field>
        <ActionRow msg={msg}><button onClick={add} className="btn-primary">保存模板</button></ActionRow>
      </Panel>
    </div>
  );
}

function UsersPanel() {
  const { data, mutate } = useSWR("/api/config/users", fetcher);
  const [form, setForm] = useState<any>({ username: "", password: "", display_name: "", email: "", role: "user" });
  const [msg, setMsg] = useState("");
  async function add() {
    setMsg("");
    try { await api.post("/api/config/users", form); setForm({ username: "", password: "", display_name: "", email: "", role: "user" }); await mutate(); } catch (e: any) { setMsg(e.message); }
  }
  async function reset(uid: number) {
    const pw = prompt("新密码:");
    if (!pw) return;
    await api.post(`/api/config/users/${uid}/password`, { new_password: pw });
    alert("已重置");
  }
  async function del(uid: number) {
    if (!confirm("禁用这个用户?")) return;
    await api.del(`/api/config/users/${uid}`);
    await mutate();
  }
  return (
    <div className="space-y-5">
      <div className="grid gap-2">
        {data?.map((u: any) => (
          <div key={u.id} className="flex flex-wrap items-center gap-2 rounded border p-3 text-sm">
            <div className="flex-1 font-medium">{u.username} <span className="text-slate-400">{u.email}</span></div>
            <Badge ok={u.active}>{u.role}</Badge>
            <button onClick={()=>reset(u.id)} className="btn-secondary">改密码</button>
            <button onClick={()=>del(u.id)} className="btn-danger">禁用</button>
          </div>
        ))}
      </div>
      <Panel title="新增用户">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="用户名"><input className="input" value={form.username} onChange={e=>setForm({...form, username: e.target.value})} /></Field>
          <Field label="密码"><input className="input" type="password" value={form.password} onChange={e=>setForm({...form, password: e.target.value})} /></Field>
          <Field label="显示名"><input className="input" value={form.display_name} onChange={e=>setForm({...form, display_name: e.target.value})} /></Field>
          <Field label="邮箱"><input className="input" value={form.email} onChange={e=>setForm({...form, email: e.target.value})} /></Field>
          <Field label="角色"><select className="input" value={form.role} onChange={e=>setForm({...form, role: e.target.value})}><option value="user">普通用户</option><option value="admin">管理员</option></select></Field>
        </div>
        <ActionRow msg={msg}><button onClick={add} className="btn-primary">添加用户</button></ActionRow>
      </Panel>
    </div>
  );
}

function DiagnosticsPanel() {
  const { data, mutate } = useSWR("/api/config/diagnostics", fetcher);
  return (
    <div className="space-y-5">
      <button onClick={()=>mutate()} className="btn-secondary">刷新</button>
      <div className="grid gap-2 md:grid-cols-2">
        {data?.checks?.map((c: any) => (
          <div key={c.name} className="rounded border p-3 text-sm">
            <div className="flex items-center gap-2"><Badge ok={c.ok}>{c.ok ? "OK" : "FAIL"}</Badge><span className="font-medium">{c.name}</span></div>
            <div className="mt-1 break-all text-xs text-slate-500">{c.detail}</div>
          </div>
        ))}
      </div>
      <div className="grid gap-2 md:grid-cols-5">
        {Object.entries(data?.counts || {}).map(([k, v]) => (
          <div key={k} className="rounded border bg-slate-50 p-3 text-sm"><div className="text-xs text-slate-500">{k}</div><div className="text-lg font-semibold">{String(v)}</div></div>
        ))}
      </div>
    </div>
  );
}

function StatusGrid({ items }: { items: [string, string, boolean][] }) {
  return (
    <div className="grid gap-2 md:grid-cols-3">
      {items.map(([name, detail, ok]) => (
        <div key={name} className="rounded border p-3 text-sm">
          <div className="flex items-center gap-2"><Badge ok={ok}>{ok ? "OK" : "TODO"}</Badge><span className="font-medium">{name}</span></div>
          <div className="mt-1 text-xs text-slate-500">{detail}</div>
        </div>
      ))}
    </div>
  );
}

function Badge({ ok, children }: { ok?: boolean; children: any }) {
  return <span className={`rounded px-2 py-0.5 text-xs ${ok ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{children}</span>;
}

function Panel({ title, children }: { title?: string; children: any }) {
  return (
    <div className="space-y-4 max-w-3xl">
      {title && <div className="text-sm font-semibold">{title}</div>}
      {children}
    </div>
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

function ActionRow({ msg, children }: { msg?: string; children: any }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      {msg && <span className="text-sm text-slate-600">{msg}</span>}
    </div>
  );
}
