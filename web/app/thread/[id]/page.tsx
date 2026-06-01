"use client";
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetcher, api, priorityColor, priorityLabel } from "@/lib/api";

export default function ThreadDetail() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const tid = params.id;
  const { data, mutate } = useSWR(`/api/threads/${tid}`, fetcher);
  const { data: senders } = useSWR("/api/senders", fetcher);
  const [showReply, setShowReply] = useState(false);
  const [replyFrom, setReplyFrom] = useState<number | null>(null);
  const [replyTo, setReplyTo] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (senders?.length && replyFrom == null) {
      const def = senders.find((s: any) => s.is_default) || senders[0];
      setReplyFrom(def.id);
    }
  }, [senders]);

  useEffect(() => {
    if (data?.messages?.length && !replyTo) {
      const last = [...data.messages].reverse().find((m: any) => m.direction === "in");
      if (last) setReplyTo(last.from_email);
    }
  }, [data]);

  async function send() {
    if (!replyFrom || !replyTo || !replyBody) return;
    setSending(true); setMsg("");
    try {
      await api.post(`/api/threads/${tid}/reply`, {
        sender_id: replyFrom,
        to: replyTo.split(",").map(s => s.trim()).filter(Boolean),
        cc: [],
        body_text: replyBody,
      });
      setReplyBody("");
      setShowReply(false);
      setMsg("✓ 已发送");
      mutate();
    } catch (e: any) {
      setMsg("✗ " + (e.message || "发送失败"));
    } finally { setSending(false); }
  }

  async function archive() {
    await api.post(`/api/threads/${tid}/archive`);
    router.push("/");
  }

  if (!data) return <div className="p-8 text-slate-500">加载中...</div>;
  const t = data.thread;
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-4xl mx-auto p-6">
        <div className="mb-4 flex items-center gap-3">
          <Link href="/" className="text-sm text-slate-500 hover:text-slate-800">← 返回收件箱</Link>
          <div className="ml-auto flex gap-2">
            <button onClick={()=>setShowReply(true)} className="text-sm bg-sky-600 text-white px-3 py-1.5 rounded hover:bg-sky-700">✏️ 回复</button>
            {t.status === "inbox" && (
              <button onClick={archive} className="text-sm border px-3 py-1.5 rounded hover:bg-slate-100">📦 归档</button>
            )}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow-sm p-6 mb-4">
          <div className="flex items-start gap-2">
            <h1 className="text-xl font-semibold flex-1">{t.subject_initial || "(无主题)"}</h1>
            <span className={`text-xs px-2 py-1 rounded border ${priorityColor(t.ai_priority)}`}>{priorityLabel(t.ai_priority)}</span>
          </div>
          {t.ai_summary && (
            <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded text-sm">
              <div className="text-amber-800">💡 <b>AI 摘要</b>: {t.ai_summary}</div>
              {t.ai_action && <div className="text-emerald-800 mt-1">→ <b>建议</b>: {t.ai_action}</div>}
              {t.due_at && <div className="text-red-700 mt-1">⏰ <b>截止</b>: {new Date(t.due_at).toLocaleString("zh-CN")}</div>}
              {t.ai_category && <div className="text-slate-600 mt-1">📂 {t.ai_category}</div>}
            </div>
          )}
          <div className="mt-2 text-xs text-slate-500">
            {t.message_count} 封 · 参与者: {(t.participants || []).join(", ")}
          </div>
        </div>

        {showReply && (
          <div className="bg-white rounded-lg shadow-sm p-4 mb-4 border-l-4 border-sky-500">
            <div className="flex gap-2 mb-2">
              <select value={replyFrom ?? ""} onChange={e=>setReplyFrom(Number(e.target.value))} className="text-sm border rounded px-2 py-1">
                {senders?.map((s: any) => <option key={s.id} value={s.id}>{s.display_name ? `${s.display_name} <${s.email}>` : s.email}</option>)}
              </select>
              <input value={replyTo} onChange={e=>setReplyTo(e.target.value)} placeholder="收件人 (逗号分隔)" className="flex-1 text-sm border rounded px-2 py-1" />
            </div>
            <textarea value={replyBody} onChange={e=>setReplyBody(e.target.value)} rows={8} placeholder="回复内容..." className="w-full text-sm border rounded p-2"></textarea>
            <div className="mt-2 flex gap-2 items-center">
              <button onClick={send} disabled={sending} className="text-sm bg-sky-600 text-white px-3 py-1.5 rounded hover:bg-sky-700 disabled:opacity-50">
                {sending ? "发送中..." : "发送"}
              </button>
              <button onClick={()=>setShowReply(false)} className="text-sm text-slate-500 hover:text-slate-800">取消</button>
              {msg && <span className="text-xs text-slate-600">{msg}</span>}
            </div>
          </div>
        )}

        <div className="space-y-3">
          {data.messages?.map((m: any) => (
            <div key={m.id} className={`bg-white rounded-lg shadow-sm p-4 ${m.direction === "out" ? "border-l-4 border-emerald-500" : ""}`}>
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{m.from_name || m.from_email}</span>
                <span className="text-slate-400 text-xs">&lt;{m.from_email}&gt;</span>
                {m.direction === "out" && <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded">已发送</span>}
                <span className="text-xs text-slate-400 ml-auto">{new Date(m.received_at).toLocaleString("zh-CN")}</span>
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                → {(m.to_emails || []).join(", ")}{m.cc_emails?.length ? ` (cc: ${m.cc_emails.join(", ")})` : ""}
              </div>
              <div className="text-sm text-slate-700 font-medium mt-2">{m.subject}</div>
              <div className="mt-3 text-sm whitespace-pre-wrap break-words text-slate-800">
                {m.body_text || (m.body_html ? <div className="text-slate-500 italic">[此邮件为 HTML 格式,见下方]</div> : <div className="text-slate-400 italic">[空内容]</div>)}
              </div>
              {m.body_html && !m.body_text && (
                <iframe srcDoc={m.body_html} className="w-full mt-3 border rounded" style={{minHeight:300}} sandbox="" />
              )}
            </div>
          ))}
        </div>

        {data.attachments?.length > 0 && (
          <div className="mt-4 bg-white rounded-lg shadow-sm p-4">
            <div className="text-sm font-medium mb-2">📎 附件 ({data.attachments.length})</div>
            <ul className="space-y-1 text-sm">
              {data.attachments.map((a: any) => (
                <li key={a.id}>
                  <a href={`/api/threads/${tid}/attachment/${a.id}`} className="text-sky-600 hover:underline" target="_blank">{a.filename}</a>
                  <span className="text-xs text-slate-400 ml-2">{(a.size_bytes/1024).toFixed(1)} KB</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
