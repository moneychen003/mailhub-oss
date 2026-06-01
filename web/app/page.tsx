"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate as swrMutate } from "swr";
import useSWRInfinite from "swr/infinite";
import { fetcher, api, timeAgo } from "@/lib/api";
import RichEditor, { RichEditorHandle } from "@/components/RichEditor";

// Strip HTML tags to plain text for body_text fallback (search/snippet uses this)
function htmlToText(html: string): string {
  if (!html) return "";
  return html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|tr)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function emailList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value !== "string") return [];
  const raw = value.trim();
  if (!raw || raw === "{}") return [];
  if (!raw.startsWith("{") || !raw.endsWith("}")) return [raw];

  const out: string[] = [];
  let cur = "";
  let quoted = false;
  let escaped = false;
  for (const ch of raw.slice(1, -1)) {
    if (escaped) {
      cur += ch;
      escaped = false;
      continue;
    }
    if (quoted && ch === "\\") {
      escaped = true;
      continue;
    }
    if (ch === '"') {
      quoted = !quoted;
      continue;
    }
    if (!quoted && ch === ",") {
      if (cur) out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  if (cur) out.push(cur);
  return out.map((s) => s.trim()).filter(Boolean);
}

function srcLabel(s: string): string {
  return ({
    "live": "自建邮箱",
    "163": "📮 163",
    "qq": "🐧 QQ",
    "gmail-9519950": "✉️ Gmail 9519950",
    "gmail-mc007": "✉️ Gmail mc007",
  } as Record<string,string>)[s] || s;
}

const THEME_OPTIONS = [
  { key: "apple-mail", label: "Mail", detail: "macOS" },
  { key: "ipados", label: "iPad", detail: "看板" },
  { key: "liquid-glass", label: "Glass", detail: "空间" },
] as const;

type ThemeKey = typeof THEME_OPTIONS[number]["key"];
type ViewKey = "inbox"|"flagged"|"sent"|"pinned"|"snoozed"|"dueToday";

const DEFAULT_THEME: ThemeKey = "apple-mail";
const THREAD_PAGE_SIZE = 80;

function isThemeKey(value: string | null): value is ThemeKey {
  return THEME_OPTIONS.some((t) => t.key === value);
}

function PriorityBar({ p }: { p?: string | null }) {
  const color = ({
    urgent: "bg-red-500",
    high: "bg-orange-500",
    normal: "bg-blue-400",
    low: "bg-neutral-300",
    spam: "bg-neutral-200",
  } as Record<string,string>)[p || "normal"] || "bg-neutral-300";
  return <div className={`w-[3px] self-stretch ${color} rounded-full`} />;
}

function PriorityChip({ p }: { p?: string | null }) {
  const labelMap: Record<string,string> = {
    urgent: "紧急", high: "高优", normal: "普通", low: "低", spam: "营销",
  };
  const cls: Record<string,string> = {
    urgent: "text-red-700 bg-red-100",
    high: "text-orange-700 bg-orange-100",
    normal: "text-blue-700 bg-blue-100",
    low: "text-neutral-600 bg-neutral-100",
    spam: "text-neutral-400 bg-neutral-100",
  };
  const k = p || "normal";
  return <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${cls[k] || cls.normal}`}>{labelMap[k] || k}</span>;
}

// Generate gradient avatar background from email/name first letter
function avatarColor(seed: string): string {
  const gradients = [
    "from-blue-400 to-purple-500",
    "from-pink-400 to-rose-500",
    "from-emerald-400 to-teal-500",
    "from-orange-400 to-red-500",
    "from-indigo-400 to-sky-500",
    "from-amber-400 to-orange-500",
    "from-fuchsia-400 to-pink-500",
    "from-cyan-400 to-blue-500",
  ];
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = ((h << 5) - h + seed.charCodeAt(i)) | 0;
  return gradients[Math.abs(h) % gradients.length];
}

function Avatar({ name, email, size = "md" }: { name?: string | null; email?: string | null; size?: "sm" | "md" | "lg" }) {
  const src = (name || email || "?").trim();
  const ch = (src[0] || "?").toUpperCase();
  const sizes = { sm: "w-7 h-7 text-[12px]", md: "w-10 h-10 text-[15px]", lg: "w-12 h-12 text-[17px]" };
  return (
    <div className={`${sizes[size]} rounded-full bg-gradient-to-br ${avatarColor(src)} text-white font-semibold flex items-center justify-center shrink-0`}>
      {ch}
    </div>
  );
}

export default function Inbox() {
  const router = useRouter();
  const [status, setStatus] = useState("inbox");
  const [priority, setPriority] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [view, setView] = useState<ViewKey>("inbox");
  const [folderId, setFolderId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [hideMarketing, setHideMarketing] = useState(true);
  const [theme, setTheme] = useState<ThemeKey>(DEFAULT_THEME);
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [me, setMe] = useState<any>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [focusedMessageId, setFocusedMessageId] = useState<number | null>(null);

  function openThreadMessage(threadId: number, messageId?: number | null) {
    setSelected(threadId);
    setFocusedMessageId(messageId || null);
  }

  // Debounce search input by 250ms
  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    api.get("/api/auth/me").then(setMe).catch(() => router.push("/login"));
  }, []);

  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem("mailhub.theme") : null;
    if (isThemeKey(saved)) setTheme(saved);
  }, []);

  function chooseTheme(next: ThemeKey) {
    setTheme(next);
    localStorage.setItem("mailhub.theme", next);
  }

  const params = new URLSearchParams({ status, page_size: String(THREAD_PAGE_SIZE) });
  if (priority) params.set("priority", priority);
  if (source) params.set("source", source);
  if (categoryFilter) params.set("category", categoryFilter);
  if (q) params.set("q", q);
  if (folderId) params.set("folder_id", String(folderId));
  if (view === "dueToday") params.set("due", "today");
  if (view === "flagged") params.set("flagged", "true");
  if (view === "pinned") params.set("pinned", "true");
  // Keep this gate in sync with the client-side marketing filter below (the `items` filter),
  // otherwise server pagination/total counts the unfiltered set while the list shows the
  // filtered subset — making "加载更多" appear stuck (loads pages that are entirely hidden).
  if (status === "inbox" && view === "inbox" && hideMarketing && !priority && !q) {
    params.set("hide_low_value", "true");
  }
  // Snooze view: only show threads still snoozed; otherwise hide snoozed.
  params.set("snoozed", view === "snoozed" ? "only" : "active");

  const getThreadsKey = (pageIndex: number, previousPageData: any) => {
    if (!me || qDebounced) return null;
    if (previousPageData && (previousPageData.items || []).length === 0) return null;
    const page = pageIndex + 1;
    if (view === "sent") return `/api/threads?status=any&page=${page}&page_size=${THREAD_PAGE_SIZE}&direction=out`;
    const pageParams = new URLSearchParams(params);
    pageParams.set("page", String(page));
    return `/api/threads?${pageParams}`;
  };
  const {
    data: threadPages,
    mutate,
    size,
    setSize,
    isLoading,
    isValidating,
  } = useSWRInfinite(getThreadsKey, fetcher, { refreshInterval: 8000, revalidateFirstPage: true });
  const { data: summary } = useSWR(me ? "/api/stats/summary" : null, fetcher, { refreshInterval: 15000 });
  const { data: folders, mutate: mutateFolders } = useSWR<any[]>(me ? "/api/folders" : null, fetcher);  // folders
  // Full-text search (only when q is non-empty, after debounce)
  const searchUrl = (me && qDebounced) ? `/api/search?q=${encodeURIComponent(qDebounced)}&limit=50` : null;
  const { data: searchData, isLoading: searchLoading } = useSWR<any>(searchUrl, fetcher);
  const searchItems = searchData?.items || [];
  const businessGroups = searchData?.business_groups || [];

  const allThreads = (threadPages || []).flatMap((page: any) => page?.items || []);
  const threadTotal = threadPages?.[0]?.total ?? 0;
  const loadedThreadCount = allThreads.length;
  const hasMoreThreads = loadedThreadCount < threadTotal;
  const isLoadingMore = isLoading || (size > 0 && !!threadPages && typeof threadPages[size - 1] === "undefined");

  // Client-side filter: hide marketing/spam from main inbox unless toggled off
  const items = allThreads.filter((t: any) => {
    if (view === "flagged" && !t.flagged) return false;
    if (view === "pinned" && !t.pinned) return false;
    if (status === "inbox" && view === "inbox" && hideMarketing && !priority && !q) {
      if (t.ai_priority === "spam") return false;
      if (t.ai_priority === "low") return false;
      if (t.ai_category === "marketing") return false;
    }
    return true;
  });

  function handleThreadListScroll(e: any) {
    if (qDebounced || !hasMoreThreads || isLoadingMore) return;
    const el = e.currentTarget;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 520) {
      setSize((current) => current + 1);
    }
  }

  // Categorize today's todo from summary + items
  const todayCounts = {
    urgent: summary?.urgent_threads ?? 0,
    billing: summary?.billing_pending ?? 0,
    shipping: summary?.shipping_urgent ?? 0,
    security: summary?.security_alerts ?? 0,
    dueToday: summary?.due_today ?? 0,
  };

  async function logout() {
    await api.post("/api/auth/logout");
    router.push("/login");
  }

  if (!me) return <div className="p-8 text-neutral-500 text-[14px]">加载中...</div>;

  return (
    <div data-theme={theme} className="mh-app flex flex-col h-screen overflow-hidden">
      {/* Top bar: 今日待处理 (sticky + frosted) */}
      <div className="mh-topbar flex shrink-0 items-center gap-2 px-3 md:px-5 min-h-14 sticky top-0 z-30">
        <button onClick={()=>setDrawerOpen(true)} className="mh-icon-button md:hidden text-xl px-1" aria-label="打开菜单">☰</button>
        <div className="mh-brand whitespace-nowrap">
          <span className="mh-brand-mark">mailhub</span>
          <span className="mh-brand-sub hidden sm:inline">AI mailbox</span>
        </div>
        <div className="flex-1 flex items-center gap-2 md:ml-5 overflow-x-auto scrollbar-hide">
          <TodayChip color="red" label="紧急" n={todayCounts.urgent} onClick={()=>{setStatus("inbox"); setView("inbox"); setPriority("urgent"); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null)}} />
          <TodayChip color="orange" label="待付款" n={todayCounts.billing} onClick={()=>{setStatus("inbox"); setView("inbox"); setPriority("urgent,high"); setCategoryFilter("billing,finance"); setSource(""); setFolderId(null); setSelected(null)}} />
          <TodayChip color="violet" label="物流" n={todayCounts.shipping} onClick={()=>{setStatus("inbox"); setView("inbox"); setPriority(""); setCategoryFilter("shipping"); setSource(""); setFolderId(null); setSelected(null)}} />
          <TodayChip color="amber" label="安全确认" n={todayCounts.security} onClick={()=>{setStatus("inbox"); setView("inbox"); setPriority("urgent,high"); setCategoryFilter("security,system"); setSource(""); setFolderId(null); setSelected(null)}} />
          <TodayChip color="rose" label="今天到期" n={todayCounts.dueToday} onClick={()=>{setStatus("inbox"); setView("dueToday"); setPriority(""); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null)}} />
        </div>
        <ThemeSwitcher theme={theme} onChange={chooseTheme} />
        <div className="text-[13px] text-neutral-500 hidden md:block font-medium">{me.display_name || me.username}</div>
        <button onClick={logout} className="text-[12px] text-neutral-400 hover:text-[#FF3B30] hidden md:inline font-medium transition-colors">退出</button>
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden relative">
        {/* Sidebar */}
        <aside className={`mh-sidebar ${drawerOpen ? "translate-x-0" : "-translate-x-full"} md:translate-x-0 transition-transform fixed md:static z-30 inset-y-0 left-0 w-64 md:w-56 min-h-0 flex flex-col overflow-y-auto shadow-2xl md:shadow-none`}>
          <div className="md:hidden flex items-center gap-2 px-4 py-3 border-b border-neutral-200/60">
            <div className="mh-brand flex-1">mailhub</div>
            <button onClick={()=>setDrawerOpen(false)} className="mh-icon-button text-xl" aria-label="关闭菜单">✕</button>
          </div>
          <div className="md:hidden px-4 py-2 text-[12px] text-neutral-500">
            {me.display_name || me.username} · <button onClick={logout} className="text-[#FF3B30] font-medium">退出</button>
          </div>
          <nav className="p-2 space-y-0.5 text-[14px]">
            <SideBtn active={status==="inbox" && !priority && !source && !categoryFilter && view==="inbox" && !folderId} onClick={()=>{setView("inbox"); setStatus("inbox"); setPriority(""); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="📥" label="主收件箱" count={hideMarketing ? summary?.inbox_visible_threads : summary?.inbox_threads} />
            </SideBtn>
            <SideBtn active={priority==="urgent"} onClick={()=>{setView("inbox"); setStatus("inbox"); setPriority("urgent"); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="🚨" label="紧急" count={summary?.urgent_threads} tone="red" />
            </SideBtn>
            <SideBtn active={priority==="high"} onClick={()=>{setView("inbox"); setStatus("inbox"); setPriority("high"); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="❗" label="高优" count={summary?.high_threads} tone="orange" />
            </SideBtn>
            <SideBtn active={view==="flagged"} onClick={()=>{setView("flagged"); setStatus("inbox"); setPriority(""); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="🚩" label="红旗" tone="rose" />
            </SideBtn>
            <SideBtn active={view==="pinned"} onClick={()=>{setView("pinned"); setStatus("inbox"); setPriority(""); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="📌" label="置顶" tone="amber" />
            </SideBtn>
            <SideBtn active={view==="snoozed"} onClick={()=>{setView("snoozed"); setStatus("inbox"); setPriority(""); setCategoryFilter(""); setSource(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow icon="😴" label="暂停中" tone="indigo" />
            </SideBtn>

            <div className="mh-side-heading">邮箱来源</div>
            <SideBtn active={status==="inbox" && !source && !priority && !categoryFilter && !folderId && view==="inbox"} onClick={()=>{setView("inbox"); setStatus("inbox"); setSource(""); setPriority(""); setCategoryFilter(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
              <SideRow label="全部来源" />
            </SideBtn>
            {summary?.sources?.map((s: any) => (
              <SideBtn key={s.source} active={source === s.source} onClick={()=>{setView("inbox"); setStatus("inbox"); setSource(s.source); setPriority(""); setCategoryFilter(""); setFolderId(null); setSelected(null); setDrawerOpen(false)}}>
                <SideRow label={srcLabel(s.source)} count={s.c} />
              </SideBtn>
            ))}

            <div className="mh-side-heading flex items-center">
              <span className="flex-1">📁 文件夹</span>
              <button onClick={async()=>{
                const name = prompt("新文件夹名:");
                if (!name) return;
                await api.post("/api/folders", { name });
                mutateFolders();
              }} className="text-[#007AFF] text-[14px] font-semibold leading-none">+</button>
            </div>
            {folders?.map((f: any) => (
              <SideBtn key={f.id} active={folderId === f.id} onClick={()=>{setFolderId(f.id); setView("inbox"); setStatus("inbox"); setSource(""); setPriority(""); setDrawerOpen(false)}}>
                <SideRow icon="📁" label={f.name} count={f.count} />
              </SideBtn>
            ))}

            <div className="mh-side-heading">其他</div>
            <SideBtn active={status==="sent" || view==="sent"} onClick={()=>{setView("sent"); setStatus("sent"); setSource(""); setPriority(""); setCategoryFilter(""); setFolderId(null); setDrawerOpen(false)}}>
              <SideRow icon="📤" label="已发送" />
            </SideBtn>
            <SideBtn active={status==="archived"} onClick={()=>{setView("inbox"); setStatus("archived"); setSource(""); setPriority(""); setCategoryFilter(""); setFolderId(null); setDrawerOpen(false)}}>
              <SideRow icon="📦" label="已归档" />
            </SideBtn>
            <SideBtn active={status==="spam"} onClick={()=>{setView("inbox"); setStatus("spam"); setSource(""); setPriority(""); setCategoryFilter(""); setFolderId(null); setDrawerOpen(false)}}>
              <SideRow icon="🗑" label="垃圾箱" />
            </SideBtn>
            <SideBtn active={status==="trash"} onClick={()=>{setView("inbox"); setStatus("trash"); setSource(""); setPriority(""); setCategoryFilter(""); setFolderId(null); setDrawerOpen(false)}}>
              <SideRow icon="♻️" label="回收站" />
            </SideBtn>
            <a href="/settings" className="block px-3 py-2 rounded-xl text-[14px] text-neutral-600 hover:bg-neutral-200/40 transition-colors">
              <SideRow icon="⚙️" label="设置" />
            </a>
          </nav>
          <div className="mt-auto p-3 text-[11px] text-neutral-500 space-y-0.5">
            <SystemStatus stats={summary} />
          </div>
        </aside>
        {drawerOpen && <div onClick={()=>setDrawerOpen(false)} className="md:hidden fixed inset-0 bg-black/40 z-20" />}

        {/* Middle: thread list */}
        <section className={`mh-list-pane ${selected ? "hidden md:flex" : "flex"} w-full md:w-[440px] min-h-0 flex-col overflow-hidden`}>
          <div className="p-3 flex gap-2 items-center border-b border-neutral-200/40">
            <input value={q} onChange={e=>setQ(e.target.value)} placeholder="搜索发件人 / 主题 / 内容..." className="mh-input flex-1 text-[14px] rounded-xl px-3 py-2 focus:outline-none transition" />
            <button onClick={()=>mutate()} className="mh-icon-button text-[14px] w-9 h-9 rounded-lg transition-colors">↻</button>
          </div>
          <div className="px-4 py-2 border-b border-neutral-200/40 flex items-center gap-2 text-[12px]">
            {qDebounced ? (
              searchLoading && !searchData ? (
                <span className="text-neutral-500">🔍 正在搜索 “{qDebounced}”...</span>
              ) : (
                <span className="text-neutral-600">
                  🔍 找到 <b className="text-neutral-900">{searchData?.total ?? 0}</b> 封邮件
                  {businessGroups.length ? <> · <b className="text-emerald-700">{businessGroups.length}</b> 个业务订单</> : null}
                  {" "}“{qDebounced}”
                </span>
              )
            ) : (
              <label className="flex items-center gap-1.5 text-neutral-600 cursor-pointer">
                <input type="checkbox" checked={hideMarketing} onChange={e=>setHideMarketing(e.target.checked)} className="accent-[#007AFF]" />
                隐藏营销/低优
              </label>
            )}
            {!qDebounced && (
              <span className="text-neutral-400 ml-auto tabular-nums">
                {loadedThreadCount} / {threadTotal}
                {isValidating && !isLoadingMore ? <span className="ml-1">刷新中</span> : null}
              </span>
            )}
          </div>
          <ul onScroll={handleThreadListScroll} className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
            {qDebounced ? (
              searchLoading && !searchData ? <li className="p-5 text-[12px] text-neutral-400">搜索中...</li> :
              (searchItems.length === 0 && businessGroups.length === 0) ? <li className="p-5 text-[12px] text-neutral-400">没有匹配的邮件</li> :
              <>
              {businessGroups.length ? (
                <>
                  <li className="px-4 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-emerald-700 uppercase">业务订单</li>
                  {businessGroups.map((g: any) => (
                    <BusinessGroupRow key={`bg-${g.vendor}-${g.shipment_key}`} group={g} selected={selected} onSelect={(id)=>openThreadMessage(id)} />
                  ))}
                  {searchItems.length ? <li className="px-4 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">匹配邮件</li> : null}
                </>
              ) : null}
              {searchItems.map((r: any) => {
                const fieldChips = businessInfoRows(r.business_fields || {}).slice(0, 4);
                return (
                  <li key={`s-${r.message_id}`}>
                    <button onClick={()=>openThreadMessage(r.thread_id, Number(r.message_id) || null)} className={`mh-thread-row w-full text-left flex gap-3 px-4 py-3 transition-colors ${selected===r.thread_id ? "is-selected" : ""}`}>
                      <PriorityBar p={r.ai_priority} />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] text-neutral-600 font-medium truncate">{r.from_name || r.from_email || "(unknown)"}</div>
                        <div className="text-[15px] font-semibold text-neutral-900 truncate mt-0.5">{r.subject || r.subject_initial || "(无主题)"}</div>
                        <div className="text-[13px] text-neutral-500 leading-snug line-clamp-2 mt-1 [&_mark]:bg-yellow-200 [&_mark]:text-neutral-900 [&_mark]:rounded-sm [&_mark]:px-0.5" dangerouslySetInnerHTML={{__html: r.snippet_hl || ""}} />
                        {fieldChips.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {fieldChips.map((item) => (
                              <span key={item.key} className="inline-flex max-w-full items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-800 ring-1 ring-emerald-100">
                                <span className="text-emerald-500">{item.label}</span>
                                <span className={`truncate ${item.mono ? "font-mono" : "font-medium"}`}>{item.value}</span>
                              </span>
                            ))}
                          </div>
                        )}
                        <div className="flex items-center gap-2 mt-1.5">
                          <PriorityChip p={r.ai_priority} />
                          {r.ai_category ? <span className="text-[11px] text-neutral-400">{r.ai_category}</span> : null}
                          <span className="text-[11px] text-neutral-400 ml-auto tabular-nums">{timeAgo(r.received_at)}</span>
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
              </>
            ) : (
            <>
            {isLoading ? <li className="p-5 text-[12px] text-neutral-400">加载中...</li> :
             items.length === 0 ? <li className="p-5 text-[12px] text-neutral-400">没有需要处理的邮件 🎉</li> :
             items.map((t: any) => (
              <li key={t.id}>
                <button onClick={()=>openThreadMessage(t.id)} className={`mh-thread-row w-full text-left flex gap-3 px-4 py-3 transition-colors ${selected===t.id ? "is-selected" : ""}`}>
                  <PriorityBar p={t.ai_priority} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      {t.unread ? <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" /> : null}
                      <div className={`text-[13px] truncate text-neutral-600 ${t.unread ? "font-semibold text-neutral-900" : "font-medium"}`}>{t.last_from || "(unknown)"}</div>
                    </div>
                    <div className={`text-[15px] truncate mt-0.5 ${t.unread ? "font-semibold text-neutral-900" : "font-semibold text-neutral-900"}`}>{t.subject_initial || "(无主题)"}</div>
                    {t.ai_summary ? (
                      <div className="text-[13px] text-neutral-500 leading-snug line-clamp-2 mt-1">{t.ai_summary}</div>
                    ) : (
                      <div className="text-[13px] text-neutral-400 leading-snug line-clamp-2 mt-1">{t.last_snippet}</div>
                    )}
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <PriorityChip p={t.ai_priority} />
                      {t.ai_category ? <span className="text-[11px] text-neutral-400">{t.ai_category}</span> : null}
                      {t.source ? <span className="text-[11px] text-violet-600 font-medium">📬{t.source}</span> : null}
                      {t.due_at ? <span className="text-[11px] text-[#FF3B30] font-medium">⏰ {new Date(t.due_at).toLocaleDateString("zh-CN")}</span> : null}
                      {t.flagged ? <span className="text-rose-600 text-[12px]">🚩</span> : null}
                      {t.pinned ? <span className="text-amber-600 text-[12px]">📌</span> : null}
                      <span className="text-[11px] text-neutral-400 ml-auto tabular-nums">{timeAgo(t.last_message_at)}</span>
                    </div>
                  </div>
                </button>
              </li>
            ))}
            {hasMoreThreads ? (
              <li className="p-3">
                <button
                  onClick={() => setSize((current) => current + 1)}
                  disabled={isLoadingMore}
                  className="w-full rounded-xl bg-neutral-100 px-3 py-2 text-[12px] font-medium text-neutral-600 hover:bg-neutral-200 disabled:opacity-60"
                >
                  {isLoadingMore ? "加载中..." : `加载更多 (${loadedThreadCount} / ${threadTotal})`}
                </button>
              </li>
            ) : loadedThreadCount > 0 ? (
              <li className="px-4 py-3 text-center text-[11px] text-neutral-400">已显示全部 {loadedThreadCount} 封</li>
            ) : null}
            </>
            )}
          </ul>
        </section>

        {/* Right: preview pane */}
        <section className={`mh-preview-pane ${selected ? "flex" : "hidden md:flex"} flex-1 min-h-0 overflow-y-auto overscroll-contain absolute md:relative inset-0 md:inset-auto md:flex-col`}>
          {selected ? (
            <ThreadPreview threadId={selected} focusMessageId={focusedMessageId} onOpenThreadMessage={openThreadMessage} onChange={()=>mutate()} onClose={()=>{setSelected(null); setFocusedMessageId(null)}} />
          ) : (
            <div className="flex items-center justify-center h-full text-neutral-400 text-[14px]">
              选一封邮件查看
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function TodayChip({ label, n, color, onClick }: { label: string; n: number; color: string; onClick: ()=>void }) {
  const toneMap: Record<string,string> = {
    red: "danger",
    orange: "warning",
    violet: "shipping",
    amber: "security",
    rose: "due",
  };
  return (
    <button
      onClick={onClick}
      data-tone={toneMap[color] || "security"}
      data-empty={n > 0 ? "false" : "true"}
      className="mh-chip flex items-center gap-2 px-3 py-1.5 rounded-full text-[13px] font-medium transition-colors whitespace-nowrap"
    >
      <span className="mh-chip-dot w-2 h-2 rounded-full"></span>
      {label}
      <span className="tabular-nums font-semibold">{n}</span>
    </button>
  );
}

function ThemeSwitcher({ theme, onChange }: { theme: ThemeKey; onChange: (theme: ThemeKey) => void }) {
  return (
    <div className="mh-theme-switcher hidden lg:flex" role="tablist" aria-label="界面模板">
      {THEME_OPTIONS.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={theme === item.key}
          onClick={() => onChange(item.key)}
          className={theme === item.key ? "is-active" : ""}
        >
          <span>{item.label}</span>
          <small>{item.detail}</small>
        </button>
      ))}
    </div>
  );
}

function SideBtn({ children, active, onClick }: any) {
  return (
    <button onClick={onClick} className={`mh-side-button w-full text-left px-3 py-2 rounded-xl transition-colors ${active ? "is-active" : ""}`}>
      {children}
    </button>
  );
}

function SideRow({ icon, label, count, tone }: { icon?: string; label: string; count?: number | string | null; tone?: string }) {
  const toneCls: Record<string,string> = {
    red: "text-red-600",
    orange: "text-orange-600",
    rose: "text-rose-600",
    amber: "text-amber-600",
    indigo: "text-indigo-600",
  };
  return (
    <div className="flex items-center gap-3">
      {icon ? <span className="text-[18px] leading-none">{icon}</span> : <span className="w-[18px]"></span>}
      <span className={`flex-1 truncate ${tone ? toneCls[tone] || "" : ""}`}>{label}</span>
      {count != null ? <span className="mh-count-badge text-[11px] rounded-full px-2 py-0.5 tabular-nums font-medium">{count}</span> : null}
    </div>
  );
}

function SystemStatus({ stats }: { stats: any }) {
  return (
    <div className="space-y-0.5 px-1">
      <div>📊 总线程 <span className="tabular-nums">{stats?.total_threads ?? "-"}</span></div>
      <div>📨 入 <span className="tabular-nums">{stats?.total_messages_in ?? "-"}</span> · 📤 出 <span className="tabular-nums">{stats?.total_messages_out ?? "-"}</span></div>
      <div className="text-emerald-600">● 收信 · ● AI · ● TG</div>
    </div>
  );
}

// Re-fetch every list/sidebar SWR cache after any mutating action (pin/archive/snooze/move/...).
// Keeps today chip, sidebar counts, search results and folders all consistent.
function refreshAll() {
  swrMutate((k: any) => typeof k === "string" && (
    k.startsWith("/api/threads") || k.startsWith("/api/search") ||
    k.startsWith("/api/stats") || k.startsWith("/api/folders") ||
    k.startsWith("/api/drafts") || k.startsWith("/api/rules")
  ));
}

function ThreadPreview({
  threadId,
  focusMessageId,
  onOpenThreadMessage,
  onChange,
  onClose,
}: {
  threadId: number;
  focusMessageId: number | null;
  onOpenThreadMessage: (threadId: number, messageId?: number | null)=>void;
  onChange: ()=>void;
  onClose: ()=>void;
}) {
  const { data, error, mutate, isLoading } = useSWR(`/api/threads/${threadId}`, fetcher);
  const { data: senders } = useSWR("/api/senders", fetcher);
  const [showReply, setShowReply] = useState(false);
  const [replyFrom, setReplyFrom] = useState<number | null>(null);
  const [replyTo, setReplyTo] = useState("");
  const [replyCc, setReplyCc] = useState("");
  const [replyBcc, setReplyBcc] = useState("");
  const [showCcBcc, setShowCcBcc] = useState(false);
  const [replyBody, setReplyBody] = useState("");
  const [includeSig, setIncludeSig] = useState(true);
  const [attachments, setAttachments] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState("");
  // 两种 banner 共用：
  //   mode='queued'  → 真延迟发送, 用 cancel-undo-send 撤销 (邮件没出去)
  //   mode='sent'    → 已投递, 用 recall 补发撤回通知 (历史路径, 文案上明确"补发")
  const [lastSent, setLastSent] = useState<
    | { mode: 'queued'; scheduled_send_id: number; thread_id: number; ts: number; window_ms: number }
    | { mode: 'sent'; msg_id: number; thread_id: number; ts: number; window_ms: number }
    | null
  >(null);
  const [undoTick, setUndoTick] = useState(0);
  const [recalling, setRecalling] = useState(false);
  const [ruleMenuOpen, setRuleMenuOpen] = useState(false);
  // Templates dropdown
  const [tplOpen, setTplOpen] = useState(false);
  const { data: templates } = useSWR<any[]>(showReply ? "/api/templates" : null, fetcher);
  // Drafts auto-save
  const [draftId, setDraftId] = useState<number | null>(null);
  const [draftSavedAt, setDraftSavedAt] = useState<Date | null>(null);
  const [draftSaving, setDraftSaving] = useState(false);
  const draftLoadedRef = useRef(false);
  const draftDirtyRef = useRef(false);
  const editorRef = useRef<RichEditorHandle | null>(null);

  useEffect(() => {
    setShowReply(false); setRuleMenuOpen(false); setMsg(""); setTplOpen(false);
    setLastSent(null);
    // Reset draft state when switching threads (but don't wipe DB draft)
    setDraftId(null); setDraftSavedAt(null); setDraftSaving(false);
    draftLoadedRef.current = false; draftDirtyRef.current = false;
    setReplyBody(""); setReplyCc(""); setReplyBcc(""); setAttachments([]);
    if (senders?.length && replyFrom == null) {
      const def = senders.find((s: any) => s.is_default) || senders[0];
      setReplyFrom(def.id);
    }
  }, [threadId, senders]);

  // Load existing draft when reply panel opens
  useEffect(() => {
    if (!showReply || draftLoadedRef.current) return;
    draftLoadedRef.current = true;
    (async () => {
      try {
        const rows: any[] = await api.get(`/api/drafts?thread_id=${threadId}`);
        const d = rows?.[0];
        if (!d) return;
        setDraftId(d.id);
        if (d.sender_id) setReplyFrom(d.sender_id);
        if (d.to_emails?.length) setReplyTo(d.to_emails.join(", "));
        if (d.cc_emails?.length) { setReplyCc(d.cc_emails.join(", ")); setShowCcBcc(true); }
        if (d.bcc_emails?.length) { setReplyBcc(d.bcc_emails.join(", ")); setShowCcBcc(true); }
        if (d.body_html) setReplyBody(d.body_html);
        else if (d.body_text) setReplyBody(d.body_text);
        if (d.updated_at) setDraftSavedAt(new Date(d.updated_at));
      } catch {}
    })();
  }, [showReply, threadId]);

  // Auto-save draft (debounce 3s)
  useEffect(() => {
    if (!showReply || !draftLoadedRef.current) return;
    const hasContent = (replyBody && replyBody.trim()) || replyTo.trim() || replyCc.trim() || replyBcc.trim();
    if (!hasContent && !draftId) return;
    draftDirtyRef.current = true;
    const t = setTimeout(async () => {
      if (!draftDirtyRef.current) return;
      draftDirtyRef.current = false;
      setDraftSaving(true);
      const payload = {
        thread_id: threadId,
        sender_id: replyFrom,
        to_emails: replyTo.split(",").map(s => s.trim()).filter(Boolean),
        cc_emails: replyCc.split(",").map(s => s.trim()).filter(Boolean),
        bcc_emails: replyBcc.split(",").map(s => s.trim()).filter(Boolean),
        body_html: replyBody,
        body_text: htmlToText(replyBody),
      };
      try {
        if (draftId) {
          await api.put(`/api/drafts/${draftId}`, payload);
        } else {
          const r: any = await api.post("/api/drafts", payload);
          if (r?.id) setDraftId(r.id);
        }
        setDraftSavedAt(new Date());
      } catch (e: any) {
        draftDirtyRef.current = true;
      }
      setDraftSaving(false);
    }, 3000);
    return () => clearTimeout(t);
  }, [replyBody, replyTo, replyCc, replyBcc, replyFrom, showReply, threadId, draftId]);

  // Undo-send countdown ticker (1Hz while a recent send exists)
  useEffect(() => {
    if (!lastSent) return;
    const t = setInterval(() => {
      const remain = lastSent.window_ms - (Date.now() - lastSent.ts);
      if (remain <= 0) { setLastSent(null); return; }
      setUndoTick(x => x + 1);
    }, 500);
    return () => clearInterval(t);
  }, [lastSent]);

  useEffect(() => {
    const messages = Array.isArray(data?.messages) ? data.messages : [];
    if (messages.length) {
      const last = [...messages].reverse().find((m: any) => m.direction === "in");
      if (last && !replyTo) setReplyTo(last.from_email);
    }
  }, [data]);

  useEffect(() => {
    if (!focusMessageId) return;
    const messages = Array.isArray(data?.messages) ? data.messages : [];
    if (!messages.some((m: any) => Number(m.id) === Number(focusMessageId))) return;
    const timer = window.setTimeout(() => {
      const el = document.getElementById(`message-${focusMessageId}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [focusMessageId, data, threadId]);

  async function send() {
    if (!replyFrom || !replyTo || !replyBody) return;
    setSending(true); setMsg("");
    const UNDO_WINDOW_SEC = 15;
    try {
      // Only real attachments (not large_link) get attached as MIME parts
      const attachmentIds = attachments
        .filter((a: any) => a.type !== "large_link" && a.id)
        .map((a: any) => a.id);
      const resp = await api.post(`/api/threads/${threadId}/reply`, {
        sender_id: replyFrom,
        to: replyTo.split(",").map(s=>s.trim()).filter(Boolean),
        cc: replyCc.split(",").map(s=>s.trim()).filter(Boolean),
        bcc: replyBcc.split(",").map(s=>s.trim()).filter(Boolean),
        body_text: htmlToText(replyBody),
        body_html: replyBody,
        attachment_ids: attachmentIds,
        include_signature: includeSig,
        delay_send_seconds: UNDO_WINDOW_SEC,  // 走「真延迟发送」路径
      });
      // Clear draft (DB + local)
      if (draftId) {
        try { await api.del(`/api/drafts/${draftId}`); } catch {}
      }
      setDraftId(null); setDraftSavedAt(null);
      draftLoadedRef.current = false; draftDirtyRef.current = false;
      setReplyBody(""); setReplyCc(""); setReplyBcc(""); setAttachments([]);
      setShowReply(false); setMsg("");
      if (resp && resp.scheduled_send_id) {
        // 新路径：邮件还没出去, 排在 scheduled_sends 队列
        setLastSent({ mode: 'queued', scheduled_send_id: resp.scheduled_send_id, thread_id: threadId, ts: Date.now(), window_ms: UNDO_WINDOW_SEC * 1000 });
      } else if (resp && resp.id) {
        // 老路径兼容：服务端立即投递, banner 走"补发撤回通知"
        setLastSent({ mode: 'sent', msg_id: resp.id, thread_id: threadId, ts: Date.now(), window_ms: 15000 });
      } else {
        setMsg("✓ 已发送");
      }
      mutate(); onChange(); refreshAll();
    } catch (e: any) { setMsg("✗ " + e.message); }
    setSending(false);
  }

  async function recallSent() {
    if (!lastSent) return;
    setRecalling(true);
    try {
      if (lastSent.mode === 'queued') {
        await api.post(`/api/threads/${lastSent.thread_id}/cancel-undo-send/${lastSent.scheduled_send_id}`);
        setLastSent(null);
        setMsg("↶ 已撤销发送 (邮件未投递)");
      } else {
        const r = await api.post(`/api/threads/${lastSent.thread_id}/recall/${lastSent.msg_id}`);
        setLastSent(null);
        setMsg(r?.notice_sent ? "↶ 已补发撤回通知给收件人" : "↶ 已标记撤回 (通知未发出)");
      }
      mutate(); onChange(); refreshAll();
    } catch (e: any) {
      setMsg("✗ 撤销失败: " + e.message);
    }
    setRecalling(false);
  }

  async function uploadAttachment(e: any) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("/api/attachments/upload", { method: "POST", body: fd, credentials: "include" });
      if (!r.ok) throw new Error("上传失败");
      const j = await r.json();
      setAttachments([...attachments, j]);
      // Large file: append link to body so recipient can download
      if (j.type === "large_link" && j.url) {
        const sizeMB = ((j.size || 0) / 1024 / 1024).toFixed(1);
        const line = `<p>📎 大附件: <a href="${j.url}">${j.filename}</a> (${sizeMB}MB)</p>`;
        const cur = replyBody || "";
        const next = cur + line;
        setReplyBody(next);
        if (editorRef.current) editorRef.current.insert(line);
        setMsg(`🔗 大附件已生成短链 (${fmtBytes(j.size)}) 并写入正文`);
      }
    } catch (e: any) { setMsg("✗ 附件: " + e.message); }
    setUploading(false);
    e.target.value = "";
  }

  async function removeAttachment(a: any) {
    if (a.type === "large_link") {
      // Just remove from local list — large_link record stays in large_files table (could be re-shared)
      setAttachments(attachments.filter((x: any) => x !== a));
      return;
    }
    try { await api.del(`/api/attachments/${a.id}`); } catch {}
    setAttachments(attachments.filter((x: any) => x.id !== a.id));
  }

  function insertTemplate(tpl: any) {
    const content = tpl.content || "";
    const looksBlock = /<(p|div|h[1-6]|ul|ol|blockquote|table)\b/i.test(content);
    const html = looksBlock ? content : `<p>${content.replace(/\n/g, "<br/>")}</p>`;
    // Prefer in-place insert via tiptap commands (preserves cursor)
    if (editorRef.current) {
      editorRef.current.insert(html);
    } else {
      const cur = replyBody || "";
      setReplyBody(cur ? cur + html : html);
    }
    setTplOpen(false);
    if (tpl.id) { api.post(`/api/templates/${tpl.id}/use`).catch(() => {}); }
    setMsg(`📝 已插入模板「${tpl.name}」`);
  }

  async function archive() {
    await api.post(`/api/threads/${threadId}/archive`);
    onChange(); refreshAll(); onClose();
  }

  async function applyRule(scope: string, priority: string, label: string) {
    let keyword: string | undefined = undefined;
    if (scope === "subject_keyword") {
      const k = prompt("主题关键词:");
      if (!k) return;
      keyword = k;
    }
    if (!confirm(`${label} → ${priority2zh(priority)}?\n历史邮件也会重新评判.`)) return;
    try {
      const r = await api.post("/api/rules/quick", { thread_id: threadId, scope, force_priority: priority, keyword, apply_to_existing: true });
      setMsg(`✓ 规则建好,重判 ${r.affected_threads} 个 thread`);
      onChange(); refreshAll();
      setRuleMenuOpen(false);
    } catch (e: any) { setMsg("✗ " + e.message); }
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 lg:p-8 max-w-3xl mx-auto w-full">
        <div className="mh-preview-toolbar flex items-center mb-4 sticky top-0 z-10 -mx-4 md:-mx-6 lg:-mx-8 px-4 md:px-6 lg:px-8 py-2">
          <button onClick={onClose} className="md:hidden flex items-center gap-1 text-[14px] text-[#007AFF] font-medium">← 返回列表</button>
          <button onClick={onClose} className="mh-icon-button hidden md:flex w-8 h-8 rounded-full items-center justify-center ml-auto transition-colors" title="关闭">✕</button>
        </div>
        <div className="mh-card p-6 text-center">
          <div className="text-[13px] font-semibold text-red-600 mb-2">邮件详情加载失败</div>
          <div className="text-[14px] text-neutral-500">{error?.message || "请重试"}</div>
          <div className="mt-4 flex justify-center gap-2">
            <button onClick={()=>mutate()} className="mh-button-primary text-[13px] px-4 py-2 rounded-lg font-medium">重试</button>
            <button onClick={onClose} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium">返回列表</button>
          </div>
        </div>
      </div>
    );
  }

  if (isLoading || !data) return <div className="p-6 text-neutral-400 text-[14px]">加载中...</div>;
  const t = data.thread;
  if (!t) {
    return (
      <div className="p-4 md:p-6 lg:p-8 max-w-3xl mx-auto w-full">
        <div className="mh-card p-6 text-center text-[14px] text-neutral-500">
          这封邮件详情暂时没有返回完整数据。
          <button onClick={()=>mutate()} className="ml-3 text-[#007AFF] font-medium">重试</button>
        </div>
      </div>
    );
  }
  const messages = Array.isArray(data.messages) ? data.messages : [];
  const lastIn = [...messages].reverse().find((m: any) => m.direction === "in");
  const lastInTo = emailList(lastIn?.to_emails);
  const domain = (lastIn?.from_email || "").split("@")[1] || "";

  return (
    <div className="p-4 md:p-6 lg:p-8 max-w-3xl mx-auto w-full">
      <div className="mh-preview-toolbar flex items-center mb-4 sticky top-0 z-10 -mx-4 md:-mx-6 lg:-mx-8 px-4 md:px-6 lg:px-8 py-2">
        <button onClick={onClose} className="md:hidden flex items-center gap-1 text-[14px] text-[#007AFF] font-medium">← 返回列表</button>
        <button onClick={onClose} className="mh-icon-button hidden md:flex w-8 h-8 rounded-full items-center justify-center ml-auto transition-colors" title="关闭">✕</button>
      </div>

      {/* 顶部信息 + 动作 */}
      <div className="mh-card p-5 md:p-6 mb-3">
        <div className="flex items-start gap-3">
          <h1 className="text-[22px] font-semibold tracking-tight flex-1 leading-snug">{t.subject_initial || "(无主题)"}</h1>
          <PriorityChip p={t.ai_priority} />
        </div>
        {t.ai_summary && (
          <div className="mh-insight-card mt-3 p-4 text-[14px] leading-relaxed">
            <div className="text-amber-900">💡 {t.ai_summary}</div>
            {t.ai_action && <div className="text-emerald-700 mt-1.5 text-[13px]">→ {t.ai_action}</div>}
            {t.due_at && <div className="text-[#FF3B30] mt-1.5 text-[13px]">⏰ 截止 {new Date(t.due_at).toLocaleString("zh-CN")}</div>}
          </div>
        )}
        <div className="mt-3 text-[12px] text-neutral-500 flex flex-wrap gap-2 items-center">
          <span>{t.message_count} 封</span>
          {t.source ? <span className="px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium">📬 {t.source}</span> : null}
          {lastInTo.length ? <span>收件至 <b className="text-neutral-700">{lastInTo.join(", ")}</b></span> : null}
          {lastIn?.from_email ? <ContactPill email={lastIn.from_email} /> : null}
        </div>

        <BusinessTimeline threadId={threadId} onOpenMessage={onOpenThreadMessage} />

        {/* 动作按钮 */}
        <div className="flex flex-wrap gap-2 mt-4">
          <button onClick={()=>setShowReply(!showReply)} className="mh-button-primary text-[13px] px-4 py-2 rounded-lg font-medium transition-colors">✏️ 回复</button>
          <button onClick={async()=>{await api.post(`/api/threads/${threadId}/flag`); mutate(); onChange(); refreshAll();}} className={`text-[13px] px-4 py-2 rounded-lg font-medium transition-colors ${t.flagged ? "bg-rose-100 text-rose-700 hover:bg-rose-200" : "bg-neutral-100 hover:bg-neutral-200 text-neutral-700"}`}>🚩 {t.flagged ? "取消红旗" : "红旗"}</button>
          <button onClick={async()=>{await api.post(`/api/threads/${threadId}/${t.pinned ? "unpin" : "pin"}`); mutate(); onChange(); refreshAll();}} className={`text-[13px] px-4 py-2 rounded-lg font-medium transition-colors ${t.pinned ? "bg-amber-100 text-amber-700 hover:bg-amber-200" : "bg-neutral-100 hover:bg-neutral-200 text-neutral-700"}`}>📌 {t.pinned ? "取消置顶" : "置顶"}</button>
          {t.status === "inbox" && <button onClick={archive} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium transition-colors">📦 归档</button>}
          {t.status === "archived" && <button onClick={async()=>{await api.post(`/api/threads/${threadId}/unarchive`); mutate(); onChange(); refreshAll();}} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium transition-colors">📦 取消归档</button>}
          <FolderMenu threadId={threadId} onMoved={()=>{onChange(); refreshAll();}} />
          <ScheduleSendButton threadId={threadId} thread={t} lastIn={lastIn} senders={senders} onDone={(m: string)=>{setMsg(m); onChange(); refreshAll();}} />
          <SnoozeMenu thread={t} threadId={threadId} onDone={(m: string)=>{setMsg(m); mutate(); onChange(); refreshAll();}} />
          <button onClick={async()=>{if(!confirm("移到回收站?"))return; await api.del(`/api/threads/${threadId}`); onChange(); refreshAll(); onClose();}} className="text-[13px] bg-neutral-100 hover:bg-red-50 text-[#FF3B30] px-4 py-2 rounded-lg font-medium transition-colors">🗑 删除</button>
          <ExportMenu threadId={threadId} />
          <button
            onClick={()=>setRuleMenuOpen(!ruleMenuOpen)}
            className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium transition-colors"
          >
            🛡️ {ruleMenuOpen ? "收起规则" : "设规则 ▾"}
          </button>
        </div>
        {ruleMenuOpen && (
          <div className="mh-menu mt-3 p-3 text-[13px]">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-[11px] text-neutral-400 px-2 py-1 uppercase tracking-wider font-semibold">此发件人: {lastIn?.from_email || "?"}</div>
                <div className="grid gap-1">
                  <button onClick={()=>applyRule("from_email","low","此发件人")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">💬 此发件人 → 💬 低</button>
                  <button onClick={()=>applyRule("from_email","spam","此发件人")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">🗑 此发件人 → 🗑 垃圾/营销</button>
                  <button onClick={()=>applyRule("from_email","high","此发件人")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">❗ 此发件人 → ❗ 高优</button>
                  <button onClick={()=>applyRule("from_email","urgent","此发件人")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">🚨 此发件人 → 🚨 紧急 (始终重要)</button>
                </div>
              </div>
              <div>
                <div className="text-[11px] text-neutral-400 px-2 py-1 uppercase tracking-wider font-semibold">整域: @{domain || "unknown"}</div>
                <div className="grid gap-1">
                  <button onClick={()=>applyRule("from_domain","spam","整个发件域")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">🗑 整域 → 🗑 垃圾/营销</button>
                  <button onClick={()=>applyRule("from_domain","low","整个发件域")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">💬 整域 → 💬 低</button>
                  <button onClick={()=>applyRule("subject_keyword","urgent","主题关键词")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">🚨 主题含某词 → 🚨 紧急</button>
                  <button onClick={()=>applyRule("subject_keyword","spam","主题关键词")} className="mh-menu-item block w-full text-left px-3 py-2 rounded-lg">🗑 主题含某词 → 🗑 垃圾/营销</button>
                </div>
              </div>
            </div>
          </div>
        )}
        {msg && <div className="text-[12px] text-neutral-600 mt-3">{msg}</div>}
      </div>

      {/* 回复框 */}
      {showReply && (
        <div className="mh-card p-5 mb-3">
          <div className="flex gap-2 mb-2 items-center">
            <span className="text-[12px] font-medium text-neutral-500 w-14">发件人</span>
            <select value={replyFrom ?? ""} onChange={e=>setReplyFrom(Number(e.target.value))} className="flex-1 text-[14px] rounded-xl bg-neutral-100/80 border-0 px-3 py-2 focus:bg-white focus:ring-2 focus:ring-blue-500/30 focus:outline-none">
              {senders?.map((s: any) => <option key={s.id} value={s.id}>{s.display_name ? `${s.display_name} <${s.email}>` : s.email}</option>)}
            </select>
          </div>
          <div className="flex gap-2 mb-2 items-center">
            <span className="text-[12px] font-medium text-neutral-500 w-14">收件人</span>
            <input value={replyTo} onChange={e=>setReplyTo(e.target.value)} placeholder="多个用逗号" className="flex-1 text-[14px] rounded-xl bg-neutral-100/80 border-0 px-3 py-2 focus:bg-white focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
            <button onClick={()=>setShowCcBcc(!showCcBcc)} className="text-[12px] text-[#007AFF] font-medium px-2 hover:bg-blue-50 rounded-lg py-1 transition-colors">{showCcBcc ? "−CC/BCC" : "+CC/BCC"}</button>
          </div>
          {showCcBcc && (
            <>
              <div className="flex gap-2 mb-2 items-center">
                <span className="text-[12px] font-medium text-neutral-500 w-14">CC</span>
                <input value={replyCc} onChange={e=>setReplyCc(e.target.value)} placeholder="抄送" className="flex-1 text-[14px] rounded-xl bg-neutral-100/80 border-0 px-3 py-2 focus:bg-white focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
              </div>
              <div className="flex gap-2 mb-2 items-center">
                <span className="text-[12px] font-medium text-neutral-500 w-14">BCC</span>
                <input value={replyBcc} onChange={e=>setReplyBcc(e.target.value)} placeholder="密送" className="flex-1 text-[14px] rounded-xl bg-neutral-100/80 border-0 px-3 py-2 focus:bg-white focus:ring-2 focus:ring-blue-500/30 focus:outline-none" />
              </div>
            </>
          )}
          {/* Draft auto-save status bar */}
          <div className="mt-1 text-[11px] text-neutral-500 flex items-center gap-2 h-4">
            {draftSaving ? <span>💾 保存中...</span>
             : draftSavedAt ? <span>💾 已自动保存 {draftSavedAt.toLocaleTimeString("zh-CN", { hour12: false })}</span>
             : draftId ? <span>💾 草稿 #{draftId}</span>
             : null}
          </div>
          <RichEditor ref={editorRef} value={replyBody} onChange={setReplyBody} placeholder="回复内容..." />
          {attachments.length > 0 && (
            <div className="flex gap-1 flex-wrap mt-3">
              {attachments.map((a: any, i: number) => {
                const isLink = a.type === "large_link";
                return (
                  <span key={a.id ?? `link-${i}`} className={`text-[12px] px-2.5 py-1 rounded-full flex items-center gap-1 ${isLink ? "bg-emerald-100 text-emerald-700" : "bg-neutral-100 text-neutral-700"}`}>
                    {isLink ? "🔗" : "📎"} {a.filename}
                    <span className="text-neutral-400 tabular-nums">({fmtBytes(a.size || 0)})</span>
                    {isLink && a.url ? <a href={a.url} target="_blank" rel="noreferrer" className="text-emerald-700 underline" title="打开短链">↗</a> : null}
                    <button onClick={()=>removeAttachment(a)} className="text-[#FF3B30] ml-1">✕</button>
                  </span>
                );
              })}
            </div>
          )}
          <div className="mt-3 flex gap-2 items-center flex-wrap">
            <button onClick={send} disabled={sending} className="text-[13px] bg-[#007AFF] text-white px-4 py-2 rounded-lg font-medium hover:bg-blue-600 disabled:opacity-50 transition-colors">{sending ? "发送中..." : "发送"}</button>
            <label className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-3 py-2 rounded-lg font-medium cursor-pointer transition-colors">
              📎 附件
              <input type="file" onChange={uploadAttachment} className="hidden" disabled={uploading} />
            </label>
            <div className="relative">
              <button type="button" onClick={()=>setTplOpen(!tplOpen)} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-3 py-2 rounded-lg font-medium transition-colors">📝 模板 ▾</button>
              {tplOpen && (
                <div className="absolute left-0 mt-2 bg-white rounded-2xl shadow-xl ring-1 ring-black/5 z-20 w-64 p-1.5 text-[13px] max-h-72 overflow-y-auto">
                  {!templates ? (
                    <div className="px-2 py-1 text-[12px] text-neutral-400">加载中...</div>
                  ) : templates.length === 0 ? (
                    <div className="px-2 py-1 text-[12px] text-neutral-400">
                      没有模板, <a href="/settings" className="text-[#007AFF] underline">→ 去设置创建模板</a>
                    </div>
                  ) : templates.map((tpl: any) => (
                    <button key={tpl.id ?? tpl.name} onClick={()=>insertTemplate(tpl)} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">
                      <div className="flex items-center gap-1">
                        <span className="truncate flex-1 font-medium">{tpl.name}</span>
                        {tpl.shortcut ? <span className="text-[10px] text-neutral-400 font-mono">{tpl.shortcut}</span> : null}
                      </div>
                      <div className="text-[11px] text-neutral-400 truncate">{htmlToText(tpl.content).slice(0, 50)}</div>
                    </button>
                  ))}
                  {templates && templates.length > 0 ? (
                    <>
                      <hr className="my-1 border-neutral-200/60" />
                      <a href="/settings" className="block px-3 py-2 text-[12px] text-[#007AFF] hover:bg-blue-50 rounded-lg">⚙️ 管理模板...</a>
                    </>
                  ) : null}
                </div>
              )}
            </div>
            <label className="flex items-center gap-1.5 text-[12px] text-neutral-600">
              <input type="checkbox" checked={includeSig} onChange={e=>setIncludeSig(e.target.checked)} className="accent-[#007AFF]" />
              带签名
            </label>
            {uploading ? <span className="text-[12px] text-neutral-500">上传中...</span> : null}
            <button onClick={()=>setShowReply(false)} className="text-[13px] text-neutral-500 hover:text-neutral-900 font-medium ml-auto">取消</button>
          </div>
        </div>
      )}

      {/* 邮件正文 */}
      <div className="space-y-3">
        {messages.map((m: any) => {
          const toEmails = emailList(m.to_emails);
          const ccEmails = emailList(m.cc_emails);
          return (
            <div id={`message-${m.id}`} key={m.id} className={`mh-card p-5 scroll-mt-24 transition-shadow ${m.direction === "out" ? "ring-1 ring-emerald-200" : ""} ${focusMessageId === m.id ? "ring-2 ring-blue-300 shadow-xl shadow-blue-100/60" : ""}`}>
              <div className="flex items-center gap-3 text-[13px]">
                <Avatar name={m.from_name} email={m.from_email} size="md" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-[15px] text-neutral-900">{m.from_name || m.from_email}</span>
                    <span className="text-neutral-400 text-[12px]">&lt;{m.from_email}&gt;</span>
                    {m.direction === "out" && <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full text-[11px] font-medium">已发送</span>}
                    <TranslateButton messageId={m.id} />
                  </div>
                  <div className="text-[12px] text-neutral-500 mt-0.5">→ {toEmails.join(", ")}{ccEmails.length ? ` (cc: ${ccEmails.join(", ")})` : ""}</div>
                </div>
                <span className="text-[12px] text-neutral-400 tabular-nums whitespace-nowrap">{new Date(m.received_at).toLocaleString("zh-CN")}</span>
              </div>
              <MessageBody text={m.body_text} html={m.body_html} />
            </div>
          );
        })}
      </div>
      {lastSent && (() => {
        const remain = Math.max(0, Math.ceil((lastSent.window_ms - (Date.now() - lastSent.ts)) / 1000));
        void undoTick;
        const isQueued = lastSent.mode === 'queued';
        const headLabel = isQueued ? `✓ 将在 ${remain} 秒后发送` : "✓ 已发送";
        const subLabel  = isQueued ? "· 还可撤销 ·" : `· ${remain} 秒内可补发撤回通知 ·`;
        const btnLabel  = isQueued
          ? (recalling ? "撤销中…" : `↶ 撤销发送 (${remain})`)
          : (recalling ? "处理中…" : "↶ 补发撤回通知");
        return (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-neutral-900/95 backdrop-blur-xl text-white text-[13px] rounded-full shadow-2xl px-5 py-2.5 flex items-center gap-3">
            <span className="font-medium">{headLabel}</span>
            <span className="text-neutral-400 text-[11px]">{subLabel}</span>
            <button
              onClick={recallSent}
              disabled={recalling}
              className="text-blue-300 hover:text-blue-100 disabled:text-neutral-500 font-semibold"
            >
              {btnLabel}
            </button>
            <button onClick={()=>setLastSent(null)} className="text-neutral-500 hover:text-neutral-300 text-[12px] ml-1">✕</button>
          </div>
        );
      })()}
    </div>
  );
}


function FolderMenu({ threadId, onMoved }: { threadId: number; onMoved: ()=>void }) {
  const [open, setOpen] = useState(false);
  const { data: folders } = useSWR("/api/folders", fetcher);
  async function move(folder_id: number | null) {
    await api.post("/api/folders/move", { thread_id: threadId, folder_id });
    setOpen(false);
    onMoved(); refreshAll();
  }
  return (
    <div className="relative">
      <button onClick={()=>setOpen(!open)} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium transition-colors">📁 移到 ▾</button>
      {open ? (
        <div className="absolute right-0 mt-2 bg-white rounded-2xl shadow-xl ring-1 ring-black/5 z-10 w-56 p-1.5 text-[13px] max-h-72 overflow-y-auto">
          <button onClick={()=>move(null)} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg text-neutral-500">↶ 移出所有文件夹</button>
          <hr className="my-1 border-neutral-200/60" />
          {folders?.length ? folders.map((f: any) => (
            <button key={f.id} onClick={()=>move(f.id)} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">📁 {f.name}</button>
          )) : <div className="px-3 py-1 text-[12px] text-neutral-400">没有文件夹,先在 sidebar 新建</div>}
        </div>
      ) : null}
    </div>
  );
}

function ContactPill({ email }: { email: string }) {
  const { data } = useSWR(`/api/contacts/${encodeURIComponent(email)}`, fetcher);
  if (!data?.contact) return null;
  const c = data.contact;
  if (c.total_in <= 1) return null;
  return <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">📇 此人共 {c.total_in} 封 · 近 30 天 {c.recent_30d || 0}</span>;
}


function displayBusinessKey(group: any): string {
  const raw = group.order_id || group.tracking_number || group.shipment_key || "";
  return String(raw).replace(/^(trk|pc|pkg|prod|guess|thr):/i, "");
}

function BusinessGroupRow({ group, selected, onSelect }: { group: any; selected: number | null; onSelect: (id: number)=>void }) {
  const latestThreadId = Number(group.latest_thread_id);
  const key = displayBusinessKey(group);
  const eventTypes = Array.isArray(group.event_types) ? group.event_types.filter(Boolean) : [];
  const previewEvents = eventTypes.slice(0, 4).map((t: string) => EVENT_META[t]?.label || t).join(" · ");
  const latestMeta = EVENT_META[group.latest_event] || EVENT_META.other;
  return (
    <li>
      <button
        onClick={()=>latestThreadId ? onSelect(latestThreadId) : undefined}
        className={`mh-thread-row w-full text-left flex gap-3 px-4 py-3 transition-colors ${selected===latestThreadId ? "is-selected" : ""}`}
      >
        <div className="w-[3px] self-stretch bg-emerald-500 rounded-full" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[13px] font-semibold text-emerald-800 shrink-0">📦 订单组合</span>
            <span className="text-[11px] uppercase px-2 py-0.5 rounded-full bg-emerald-600 text-white font-semibold shrink-0">{group.vendor}</span>
            <span className="font-mono text-[12px] text-emerald-900 truncate">#{key}</span>
          </div>
          <div className="text-[15px] font-semibold text-neutral-900 truncate mt-1">{group.latest_subject || "业务时间线"}</div>
          <div className="text-[13px] text-neutral-500 leading-snug truncate mt-1">
            {previewEvents || latestMeta.label}
            <span className="mx-1.5 text-neutral-300">·</span>
            {group.event_count || 0} 个事件 / {group.thread_count || 0} 封邮件
          </div>
          <div className="flex items-center gap-2 mt-1.5">
            <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${latestMeta.cls}`}>{latestMeta.icon} {latestMeta.label}</span>
            {group.tracking_number ? <span className="font-mono text-[11px] text-neutral-400 truncate">{group.tracking_number}</span> : null}
            <span className="text-[11px] text-neutral-400 ml-auto tabular-nums">{timeAgo(group.last_at)}</span>
          </div>
        </div>
      </button>
    </li>
  );
}


const EVENT_META: Record<string, { icon: string; label: string; cls: string }> = {
  order_placed:     { icon: "🛒", label: "下单",     cls: "text-blue-700 bg-blue-100" },
  order_updated:    { icon: "🔄", label: "已更新",   cls: "text-cyan-700 bg-cyan-100" },
  payment_pending:  { icon: "💰", label: "待付款",   cls: "text-amber-700 bg-amber-100" },
  payment_done:     { icon: "💳", label: "已付款",   cls: "text-emerald-700 bg-emerald-100" },
  shipped:          { icon: "📦", label: "已发货",   cls: "text-indigo-700 bg-indigo-100" },
  in_warehouse:     { icon: "🏬", label: "已入库",   cls: "text-violet-700 bg-violet-100" },
  out_for_delivery: { icon: "🚚", label: "派送中",   cls: "text-orange-700 bg-orange-100" },
  delivered:        { icon: "✅", label: "已送达",   cls: "text-emerald-700 bg-emerald-100" },
  cancelled:        { icon: "🚫", label: "已取消",   cls: "text-rose-700 bg-rose-100" },
  returned:         { icon: "↩️", label: "退回/退款", cls: "text-rose-700 bg-rose-100" },
  other:            { icon: "📩", label: "事件",     cls: "text-neutral-600 bg-neutral-100" },
  payment_received: { icon: "💳", label: "已收款",   cls: "text-emerald-700 bg-emerald-100" },
};

function BusinessTimeline({ threadId, onOpenMessage }: { threadId: number; onOpenMessage: (threadId: number, messageId?: number | null)=>void }) {
  const { data } = useSWR<any>(`/api/business/timeline?thread_id=${threadId}`, fetcher, { refreshInterval: 60000 });
  const orders = data?.orders || [];
  if (!orders.length) return null;
  return (
    <div className="mt-3 space-y-3">
      {orders.map((o: any, idx: number) => {
        const latest = o.events?.[o.events.length - 1];
        const info = businessInfoRows(o.fields || {});
        return (
          <div key={idx} className="bg-emerald-50/60 rounded-2xl p-4">
            <div className="flex items-center gap-2 text-[14px] font-semibold text-emerald-900">
              <span>📦 订单时间线</span>
              <span className="text-[11px] uppercase px-2 py-0.5 rounded-full bg-emerald-600 text-white font-medium">{o.vendor}</span>
              <span className="font-mono text-[12px]">#{displayBusinessKey(o)}</span>
              <span className="ml-auto text-[12px] text-neutral-500 font-normal">{o.events.length} 个事件</span>
            </div>
            <ol className="mt-3 space-y-2">
              {o.events.map((e: any) => {
                const meta = EVENT_META[e.event_type] || EVENT_META.other;
                const eventThreadId = Number(e.thread_id);
                const eventMessageId = Number(e.id);
                return (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={()=>eventThreadId && onOpenMessage(eventThreadId, eventMessageId || null)}
                      title="打开这封邮件"
                      className="w-full flex items-center gap-3 text-[12px] rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-white/80 focus:outline-none focus:ring-2 focus:ring-emerald-300"
                    >
                      <span className={`shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${meta.cls}`}>
                        <span>{meta.icon}</span>
                        <span>{meta.label}</span>
                      </span>
                      <span className="text-neutral-500 shrink-0 tabular-nums">{new Date(e.occurred_at).toLocaleString("zh-CN")}</span>
                      <span className="text-neutral-700 truncate flex-1" title={e.msg_subject || ""}>{e.msg_subject || e.details?.subject || ""}</span>
                      {e.tracking_number ? <span className="font-mono text-[11px] text-neutral-500">{e.tracking_number}</span> : null}
                    </button>
                  </li>
                );
              })}
            </ol>
            {latest?.tracking_number && (
              <div className="mt-2 text-[11px] text-neutral-500">最新单号: <span className="font-mono">{latest.tracking_number}</span></div>
            )}
            {info.length > 0 && (
              <div className="mt-4 border-t border-emerald-100 pt-3">
                <div className="text-[12px] font-semibold text-emerald-900 mb-2">包裹信息</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {info.map((item) => (
                    <div key={item.label} className="rounded-xl bg-white/70 px-3 py-2 ring-1 ring-emerald-100/70">
                      <div className="text-[11px] text-neutral-400">{item.label}</div>
                      <div className={`mt-0.5 text-[13px] text-neutral-900 break-words ${item.mono ? "font-mono" : "font-medium"}`}>{item.value}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function businessInfoRows(fields: Record<string, any>) {
  const rows = [
    { key: "pickup_code", label: "提货密码", mono: true },
    { key: "waybill_number", label: "运单编号", mono: true },
    { key: "package_id", label: "货件编号", mono: true },
    { key: "package_weight", label: "货件重量" },
    { key: "chargeable_weight", label: "总收费重量" },
    { key: "fee", label: "收费" },
    { key: "pickup_location", label: "取货 / 送货地点" },
  ];
  return rows
    .map((row) => ({ ...row, value: fields?.[row.key] }))
    .filter((row) => row.value);
}

function priority2zh(p: string): string {
  return ({urgent:"🚨 紧急", high:"❗ 高优", normal:"📨 普通", low:"💬 低", spam:"🗑 营销"} as Record<string,string>)[p] || p;
}

function ExportMenu({ threadId }: { threadId: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button onClick={()=>setOpen(!open)} className="text-[13px] bg-neutral-100 hover:bg-neutral-200 text-neutral-700 px-4 py-2 rounded-lg font-medium transition-colors">⬇️ 导出 ▾</button>
      {open && (
        <div className="absolute right-0 mt-2 bg-white rounded-2xl shadow-xl ring-1 ring-black/5 z-10 w-56 p-1.5 text-[13px]">
          <a href={`/api/exports/thread/${threadId}.eml`} className="block px-3 py-2 hover:bg-neutral-100/80 rounded-lg" onClick={()=>setOpen(false)}>📄 .eml (最新单封)</a>
          <a href={`/api/exports/thread/${threadId}.mbox`} className="block px-3 py-2 hover:bg-neutral-100/80 rounded-lg" onClick={()=>setOpen(false)}>📚 .mbox (整个 thread)</a>
        </div>
      )}
    </div>
  );
}

// Default datetime-local prompt value = now + 5 min, local time, no seconds
function defaultLaterValue(): string {
  const d = new Date(Date.now() + 5 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function ScheduleSendButton({ threadId, thread, lastIn, senders, onDone }: { threadId: number; thread: any; lastIn: any; senders: any[] | undefined; onDone: (m: string)=>void }) {
  async function go() {
    if (!senders?.length) { onDone("✗ 没有可用发件人"); return; }
    const defSender = senders.find((s: any) => s.is_default) || senders[0];
    const to = (lastIn?.from_email || prompt("收件人 (逗号分隔):") || "").trim();
    if (!to) { onDone("✗ 取消 (没填收件人)"); return; }
    const dtStr = prompt("发送时间 (本地时区, 格式 YYYY-MM-DDTHH:MM):", defaultLaterValue());
    if (!dtStr) return;
    const d = new Date(dtStr);
    if (isNaN(d.getTime())) { onDone("✗ 时间格式无效"); return; }
    if (d.getTime() < Date.now() - 30_000) { onDone("✗ 时间不能在过去"); return; }
    const body = prompt("正文 (可在 [计划发送列表] 编辑, 这里先简易输入):", "");
    if (body === null) return;
    const subj = thread?.subject_initial ? (thread.subject_initial.toLowerCase().startsWith("re:") ? thread.subject_initial : `Re: ${thread.subject_initial}`) : null;
    try {
      const r: any = await api.post("/api/scheduled", {
        thread_id: threadId,
        sender_id: defSender.id,
        to: to.split(",").map((x: string)=>x.trim()).filter(Boolean),
        subject: subj,
        body_text: body,
        scheduled_for: d.toISOString(),
        include_signature: true,
      });
      onDone(`⏰ 已排程 #${r.id} → ${d.toLocaleString("zh-CN")}`);
    } catch (e: any) {
      onDone("✗ 排程失败: " + e.message);
    }
  }
  return <button onClick={go} className="text-[13px] bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-4 py-2 rounded-lg font-medium transition-colors">⏰ 计划发送</button>;
}

function SnoozeMenu({ thread, threadId, onDone }: { thread: any; threadId: number; onDone: (m: string)=>void }) {
  const [open, setOpen] = useState(false);
  const snoozedActive = thread?.snoozed_until && new Date(thread.snoozed_until).getTime() > Date.now();

  async function snoozeUntil(d: Date, label: string) {
    setOpen(false);
    try {
      await api.post(`/api/threads/${threadId}/snooze`, { snoozed_until: d.toISOString() }); refreshAll();
      onDone(`😴 已暂停到 ${label} (${d.toLocaleString("zh-CN")})`);
    } catch (e: any) { onDone("✗ snooze 失败: " + e.message); }
  }

  async function unsnooze() {
    setOpen(false);
    try {
      await api.post(`/api/threads/${threadId}/unsnooze`);
      refreshAll();
      onDone("😴 已取消暂停");
    } catch (e: any) { onDone("✗ " + e.message); }
  }

  function presetIn1h() {
    snoozeUntil(new Date(Date.now() + 60 * 60 * 1000), "1 小时后");
  }
  function presetTomorrow9() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    snoozeUntil(d, "明早 9 点");
  }
  function presetNextMonday9() {
    const d = new Date();
    const day = d.getDay(); // 0=Sun..6=Sat
    const diff = day === 1 ? 7 : ((8 - day) % 7 || 7);
    d.setDate(d.getDate() + diff);
    d.setHours(9, 0, 0, 0);
    snoozeUntil(d, "下周一 9 点");
  }
  function presetCustom() {
    const dtStr = prompt("暂停到 (本地时区, 格式 YYYY-MM-DDTHH:MM):", defaultLaterValue());
    if (!dtStr) { setOpen(false); return; }
    const d = new Date(dtStr);
    if (isNaN(d.getTime())) { onDone("✗ 时间格式无效"); setOpen(false); return; }
    if (d.getTime() <= Date.now()) { onDone("✗ 必须是未来时间"); setOpen(false); return; }
    snoozeUntil(d, "自定义");
  }

  return (
    <div className="relative">
      <button onClick={()=>setOpen(!open)} className={`text-[13px] px-4 py-2 rounded-lg font-medium transition-colors ${snoozedActive ? "bg-indigo-100 text-indigo-700 hover:bg-indigo-200" : "bg-neutral-100 hover:bg-neutral-200 text-neutral-700"}`}>
        😴 {snoozedActive ? `暂停中 (到 ${new Date(thread.snoozed_until).toLocaleString("zh-CN", {hour: "2-digit", minute: "2-digit", month: "numeric", day: "numeric"})})` : "Snooze ▾"}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 bg-white rounded-2xl shadow-xl ring-1 ring-black/5 z-10 w-56 p-1.5 text-[13px]">
          <button onClick={presetIn1h} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">⏳ 1 小时后</button>
          <button onClick={presetTomorrow9} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">🌅 明早 9 点</button>
          <button onClick={presetNextMonday9} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">📅 下周一 9 点</button>
          <button onClick={presetCustom} className="block w-full text-left px-3 py-2 hover:bg-neutral-100/80 rounded-lg">✏️ 自定义时间...</button>
          {snoozedActive && (
            <>
              <hr className="my-1 border-neutral-200/60" />
              <button onClick={unsnooze} className="block w-full text-left px-3 py-2 hover:bg-red-50 text-[#FF3B30] rounded-lg">✕ 取消暂停</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}


function TranslateButton({ messageId }: { messageId: number }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pairs, setPairs] = useState<{src: string; tgt: string}[] | null>(null);
  const [error, setError] = useState("");

  async function translate() {
    if (pairs) { setOpen(!open); return; }
    setLoading(true); setError("");
    try {
      const r = await api.post(`/api/translate/message/${messageId}?target=zh`);
      setPairs(r.pairs || []);
      setOpen(true);
    } catch (e: any) {
      setError(e?.message || "翻译失败");
      setOpen(true);
    }
    setLoading(false);
  }

  return (
    <>
      <button onClick={translate} disabled={loading}
              className="text-[11px] px-2 py-0.5 rounded-full hover:bg-blue-50 text-[#007AFF] ml-1 font-medium"
              title="AI 翻译成中文 (段落对照)">
        {loading ? "⏳" : pairs ? (open ? "🌐 收起对照" : "🌐 对照") : "🌐 译"}
      </button>
      {open && pairs && pairs.length > 0 && (
        <div className="basis-full mt-3 rounded-xl bg-white shadow-sm">
          <div className="text-[12px] text-blue-700 px-3 py-1.5 bg-blue-50 rounded-t-xl font-medium">
            🌐 中外对照 ({pairs.length} 段)
          </div>
          <div className="divide-y divide-neutral-200/60">
            {pairs.map((p, i) => (
              <div key={i} className="px-4 py-2.5 text-[14px]">
                <div className="text-neutral-500 text-[12px] italic leading-relaxed whitespace-pre-wrap mb-1">{p.src}</div>
                <div className="text-neutral-800 leading-relaxed whitespace-pre-wrap">{p.tgt}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {open && error && (
        <div className="basis-full mt-3 p-3 bg-red-50 rounded-xl text-[12px] text-red-700">
          翻译失败: {error}
        </div>
      )}
    </>
  );
}


function MessageBody({ text, html }: { text?: string | null; html?: string | null }) {
  const [showSource, setShowSource] = useState(false);

  // 检测 body_text 是否其实是 HTML 源码
  const textLooksLikeHtml = !!text && /^\s*<(\!DOCTYPE\s+html|html|head|body|table|div|meta|style)\b/i.test(text.trim().slice(0, 200));

  // 决策: 优先用真的 HTML; 如果只有 text 且 text 不是 HTML 源码, 用 text; 都没有 = 空
  const hasRealHtml = !!html && html.trim().length > 0;
  const hasUsableText = !!text && text.trim().length > 0 && !textLooksLikeHtml;

  if (!hasRealHtml && !hasUsableText && !text) {
    return <div className="text-neutral-400 italic text-[12px] mt-3">[空]</div>;
  }

  // 包一层 wrapper html 注入 CSP 允许图片 + 字体收敛
  function wrap(rawHtml: string): string {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline' data: blob: https:; img-src * data: blob:; style-src 'unsafe-inline' *; font-src * data:;"><base target="_blank"><style>body{font-family:-apple-system,'SF Pro Text','Segoe UI',sans-serif;font-size:14px;color:#1c1c1e;padding:8px;margin:0;line-height:1.6}img{max-width:100%;height:auto}a{color:#007AFF}table{max-width:100%}</style></head><body>${rawHtml}</body></html>`;
  }

  if (hasRealHtml) {
    return (
      <div className="mt-3">
        <iframe srcDoc={wrap(html!)} className="w-full rounded-xl bg-white"
                style={{ minHeight: 400 }}
                sandbox="allow-popups allow-popups-to-escape-sandbox"
                referrerPolicy="no-referrer" />
        {hasUsableText && (
          <div className="mt-1">
            <button onClick={()=>setShowSource(!showSource)} className="text-[11px] text-neutral-400 hover:text-neutral-600 font-medium">
              {showSource ? "收起纯文本版" : "查看纯文本版"}
            </button>
            {showSource && (
              <pre className="text-[12px] bg-neutral-100/80 p-3 rounded-xl mt-1 whitespace-pre-wrap break-words max-h-60 overflow-y-auto">{text}</pre>
            )}
          </div>
        )}
      </div>
    );
  }

  // 只有 text (或 text 是 HTML 源码)
  if (textLooksLikeHtml) {
    // text 其实是 HTML, 当 HTML 渲染
    return (
      <iframe srcDoc={wrap(text!)} className="w-full mt-3 rounded-xl bg-white"
              style={{ minHeight: 400 }}
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              referrerPolicy="no-referrer" />
    );
  }

  return (
    <div className="mt-3 text-[14px] leading-relaxed whitespace-pre-wrap break-words text-neutral-800">{text}</div>
  );
}
