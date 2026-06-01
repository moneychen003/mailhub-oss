"use client";

import { useMemo, useState } from "react";

type Bucket = "all" | "urgent" | "logistics" | "payment" | "security" | "done";
type Priority = "high" | "normal" | "low";

type DemoMail = {
  id: string;
  sender: string;
  subject: string;
  preview: string;
  receivedAt: string;
  bucket: Bucket;
  relatedBuckets?: Bucket[];
  priority: Priority;
  status: string;
  business: string;
  action: string;
  aiSummary: string;
  aiReason: string;
  extracted: Array<{ label: string; value: string }>;
  timeline?: Array<{ label: string; time: string; text: string; state: "done" | "current" | "next" }>;
  raw: string;
};

const buckets: Array<{ id: Bucket; label: string }> = [
  { id: "all", label: "全部样例" },
  { id: "urgent", label: "紧急" },
  { id: "logistics", label: "物流" },
  { id: "payment", label: "待付款" },
  { id: "security", label: "安全确认" },
  { id: "done", label: "无需处理" },
];

const bucketLabels: Record<Bucket, string> = {
  all: "全部样例",
  urgent: "紧急",
  logistics: "物流",
  payment: "待付款",
  security: "安全确认",
  done: "无需处理",
};

const priorityTone: Record<Priority, string> = {
  high: "bg-rose-50 text-rose-700 ring-rose-100",
  normal: "bg-blue-50 text-blue-700 ring-blue-100",
  low: "bg-neutral-100 text-neutral-600 ring-neutral-200",
};

const demoMails: DemoMail[] = [
  {
    id: "buyandship-919987958",
    sender: "Buy&Ship 香港",
    subject: "您的转运单已完成",
    preview: "货件 919987958 已签收完成，运单 1ZA8272V0348286731。",
    receivedAt: "今天 12:21",
    bucket: "done",
    relatedBuckets: ["logistics"],
    priority: "low",
    status: "已送达",
    business: "Buy&Ship 货件 #919987958",
    action: "无需操作，归档为已完成物流事件。",
    aiSummary: "系统把同一货件的入库、打包、派送、送达邮件合并为一条时间线。",
    aiReason: "邮件包含同一个货件编号和 UPS 运单号，发件域名属于 Buy&Ship 通知源。",
    extracted: [
      { label: "货件编号", value: "919987958" },
      { label: "运单号", value: "1ZA8272V0348286731" },
      { label: "业务状态", value: "已送达" },
      { label: "建议动作", value: "确认收货后归档" },
    ],
    timeline: [
      { label: "已入库", time: "5/2 09:29", text: "货件到达香港仓库，可进行集运。", state: "done" },
      { label: "已打包", time: "5/4 15:09", text: "货件已完成打包，等待安排出库。", state: "done" },
      { label: "派送中", time: "5/5 14:16", text: "领取货件通知，等待签收。", state: "done" },
      { label: "已送达", time: "今天 12:21", text: "转运单已完成。", state: "current" },
    ],
    raw: "恭喜您！您已签收转运货件。感谢使用 Buyandship，希望您满意本次服务。",
  },
  {
    id: "apple-w1234567890",
    sender: "Apple Store",
    subject: "订单 W1234567890 已发货",
    preview: "iPhone 订单已交给承运商，预计明天 18:00 前派送。",
    receivedAt: "今天 09:42",
    bucket: "logistics",
    priority: "normal",
    status: "派送中",
    business: "Apple 订单 W1234567890",
    action: "保留在物流入口，明天未签收时提醒检查派送状态。",
    aiSummary: "Apple 下单、付款、发货、送达通知会合成一个订单事件。",
    aiReason: "主题中有订单号，正文包含派送时间和承运信息，属于同一订单生命周期。",
    extracted: [
      { label: "订单号", value: "W1234567890" },
      { label: "商品", value: "iPhone 17 Pro Max 256GB" },
      { label: "预计送达", value: "明天 18:00 前" },
      { label: "建议动作", value: "等待签收" },
    ],
    timeline: [
      { label: "已下单", time: "5/1 21:08", text: "Apple Store 已确认订单。", state: "done" },
      { label: "已付款", time: "5/1 21:10", text: "付款授权成功。", state: "done" },
      { label: "已发货", time: "今天 09:42", text: "承运商已收件。", state: "current" },
      { label: "待送达", time: "明天", text: "未签收时进入提醒。", state: "next" },
    ],
    raw: "您的订单 W1234567890 已发货。承运商将在预计时间内派送，请留意短信或电话通知。",
  },
  {
    id: "paypal-invoice",
    sender: "service@paypal.com",
    subject: "账单：ChatGPT Team $10.99 USD",
    preview: "一笔订阅账单等待确认，系统识别为低金额周期性付款。",
    receivedAt: "昨天",
    bucket: "payment",
    priority: "normal",
    status: "待确认",
    business: "PayPal 订阅账单",
    action: "核对是否为本人订阅，确认后标记为已处理。",
    aiSummary: "这是账单或订阅付款通知，不是普通营销邮件。",
    aiReason: "发件地址、金额、币种和订阅关键词同时出现，归入待付款/账单入口。",
    extracted: [
      { label: "金额", value: "$10.99 USD" },
      { label: "商户", value: "ChatGPT Team" },
      { label: "类型", value: "订阅账单" },
      { label: "建议动作", value: "核对授权" },
    ],
    raw: "You have a new invoice from ChatGPT Team. Amount due: $10.99 USD.",
  },
  {
    id: "cloudflare-code",
    sender: "noreply@notify.cloudflare.com",
    subject: "您的 Cloudflare 登录令牌：9620734",
    preview: "安全验证码邮件，需要确认是否本人正在登录。",
    receivedAt: "今天 08:19",
    bucket: "security",
    relatedBuckets: ["urgent"],
    priority: "high",
    status: "安全确认",
    business: "Cloudflare 登录验证",
    action: "如果不是本人操作，立即修改密码并开启双重验证。",
    aiSummary: "安全敏感邮件不应该和普通系统通知混在一起，应进入安全确认入口。",
    aiReason: "主题包含登录令牌，发件域名可信，但仍需要人工确认上下文。",
    extracted: [
      { label: "验证码", value: "9620734" },
      { label: "账户", value: "Cloudflare" },
      { label: "风险", value: "高" },
      { label: "建议动作", value: "确认本人操作" },
    ],
    raw: "Your Cloudflare login code is 9620734. If this was not you, change your password immediately.",
  },
  {
    id: "bank-transfer",
    sender: "Wise",
    subject: "转账需要补充收款人资料",
    preview: "跨境转账缺少收款地址，48 小时内不补充会退回。",
    receivedAt: "昨天 17:30",
    bucket: "urgent",
    relatedBuckets: ["payment"],
    priority: "high",
    status: "今天到期",
    business: "Wise 转账资料补充",
    action: "今天处理，补充收款人地址，避免转账退回。",
    aiSummary: "这封邮件有明确截止时间和资金流影响，应进入紧急与今天到期。",
    aiReason: "正文含 48 小时、退回、补充资料等高优先级词，同时涉及资金。",
    extracted: [
      { label: "截止时间", value: "今天 17:30" },
      { label: "影响", value: "转账退回" },
      { label: "类型", value: "资金/资料补充" },
      { label: "建议动作", value: "立即处理" },
    ],
    raw: "We need additional recipient information. If not provided within 48 hours, the transfer will be returned.",
  },
  {
    id: "marketing-sale",
    sender: "Ashley Stewart",
    subject: "FINAL HOURS! Extra 50% off CLEARANCE",
    preview: "清仓促销邮件，系统识别为营销，无需处理。",
    receivedAt: "昨天",
    bucket: "done",
    priority: "low",
    status: "营销",
    business: "促销邮件",
    action: "无需处理，默认沉底。",
    aiSummary: "这封邮件没有订单、账单、安全或截止动作，是普通营销邮件。",
    aiReason: "主题强促销词明显，正文不包含个人订单或待办动作。",
    extracted: [
      { label: "类型", value: "营销" },
      { label: "动作", value: "无需处理" },
      { label: "优先级", value: "低" },
      { label: "建议动作", value: "忽略" },
    ],
    raw: "Final hours. Extra 50% off clearance. Shop now.",
  },
];

export default function DemoClient() {
  const [activeBucket, setActiveBucket] = useState<Bucket>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(demoMails[0].id);
  const [completed, setCompleted] = useState<string[]>([]);
  const [archived, setArchived] = useState<string[]>([]);

  const visibleMails = useMemo(
    () => demoMails.filter((mail) => !archived.includes(mail.id)),
    [archived],
  );

  const filteredMails = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return visibleMails.filter((mail) => {
      const bucketMatched = activeBucket === "all" || matchesBucket(mail, activeBucket);
      const queryMatched =
        !normalizedQuery ||
        `${mail.sender} ${mail.subject} ${mail.preview} ${mail.business}`.toLowerCase().includes(normalizedQuery);
      return bucketMatched && queryMatched;
    });
  }, [activeBucket, query, visibleMails]);

  const selectedMail = filteredMails.find((mail) => mail.id === selectedId) ?? filteredMails[0] ?? null;
  const pendingCount = visibleMails.filter((mail) => mail.bucket !== "done" && !completed.includes(mail.id)).length;
  const timelineCount = visibleMails.filter((mail) => mail.timeline).length;

  function bucketCount(bucket: Bucket) {
    if (bucket === "all") return visibleMails.length;
    return visibleMails.filter((mail) => matchesBucket(mail, bucket)).length;
  }

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-neutral-950">
      <header className="border-b border-neutral-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <a href="https://github.com/" className="text-xs font-medium text-neutral-500 hover:text-neutral-950">
            返回项目主页
          </a>
          <div className="flex items-center gap-2 text-xs">
            <span className="rounded-full bg-blue-50 px-2.5 py-1 font-semibold text-blue-700">公开 Demo</span>
            <span className="hidden text-neutral-400 sm:inline">示例数据，不连接真实邮箱</span>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-4 px-4 py-8 sm:px-6 lg:grid-cols-[250px_minmax(0,1fr)_420px] lg:px-8">
        <aside className="rounded-3xl bg-white p-4 ring-1 ring-neutral-200 lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
          <div className="flex items-center gap-2">
            <div className="grid h-9 w-9 place-items-center rounded-2xl bg-blue-600 text-white">✉</div>
            <div>
              <div className="text-sm font-bold">mailhub demo</div>
              <div className="text-[11px] text-neutral-500">公开样例邮箱</div>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-2">
            <Stat label="待处理" value={`${pendingCount}`} />
            <Stat label="已合并" value={`${timelineCount}`} />
          </div>

          <nav className="mt-5 space-y-1">
            {buckets.map((bucket) => (
              <button
                key={bucket.id}
                type="button"
                onClick={() => setActiveBucket(bucket.id)}
                className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition ${
                  activeBucket === bucket.id ? "bg-blue-50 font-semibold text-blue-700" : "text-neutral-600 hover:bg-neutral-50"
                }`}
              >
                <span>{bucket.label}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-neutral-500 ring-1 ring-neutral-100">
                  {bucketCount(bucket.id)}
                </span>
              </button>
            ))}
          </nav>

          <div className="mt-5 rounded-2xl bg-neutral-950 p-4 text-white">
            <div className="text-xs font-semibold text-blue-200">Demo 玩法</div>
            <p className="mt-2 text-xs leading-relaxed text-neutral-300">
              切换分类、搜索订单号、点击邮件，看右侧 AI 如何把邮件变成业务事件。
            </p>
          </div>
        </aside>

        <section className="min-w-0 rounded-3xl bg-white p-4 ring-1 ring-neutral-200">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-xl font-bold tracking-tight">AI 收件箱</h1>
              <p className="mt-1 text-xs text-neutral-500">
                当前视图：{bucketLabels[activeBucket]}，共 {filteredMails.length} 封样例邮件
              </p>
            </div>
            <label className="relative block sm:w-72">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索 919987958 / Apple / 安全..."
                className="h-10 w-full rounded-full border border-neutral-200 bg-neutral-50 pl-9 pr-3 text-sm outline-none transition focus:border-blue-400 focus:bg-white"
              />
            </label>
          </div>

          <div className="mt-4 overflow-hidden rounded-2xl border border-neutral-200">
            {filteredMails.map((mail) => {
              const selected = mail.id === selectedMail?.id;
              const mailHandled = completed.includes(mail.id);
              return (
                <button
                  key={mail.id}
                  type="button"
                  onClick={() => setSelectedId(mail.id)}
                  className={`grid w-full gap-2 border-b border-neutral-100 p-4 text-left transition last:border-b-0 ${
                    selected ? "bg-blue-50/70" : "bg-white hover:bg-neutral-50"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-neutral-700">{mail.sender}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${priorityTone[mail.priority]}`}>
                          {mail.status}
                        </span>
                        {mailHandled ? (
                          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-100">
                            已处理
                          </span>
                        ) : null}
                      </div>
                      <h2 className="mt-1 truncate text-base font-bold text-neutral-950">{mail.subject}</h2>
                    </div>
                    <span className="shrink-0 text-xs text-neutral-400">{mail.receivedAt}</span>
                  </div>
                  <p className="line-clamp-2 text-sm leading-relaxed text-neutral-600">{mail.preview}</p>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-500">
                    <span className="rounded-full bg-neutral-100 px-2 py-1">{bucketLabels[mail.bucket]}</span>
                    <span className="rounded-full bg-neutral-100 px-2 py-1">{mail.business}</span>
                  </div>
                </button>
              );
            })}
            {filteredMails.length === 0 ? (
              <div className="grid min-h-[260px] place-items-center bg-neutral-50 p-8 text-center">
                <div>
                  <h2 className="text-base font-bold text-neutral-900">没有匹配的样例邮件</h2>
                  <p className="mt-1 max-w-sm text-sm leading-relaxed text-neutral-500">
                    换个关键词，或者切回全部样例。Demo 不会用无关邮件填充右侧详情。
                  </p>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <aside className="min-w-0 rounded-3xl bg-white p-4 ring-1 ring-neutral-200 lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)] lg:overflow-auto">
          {selectedMail ? (
            <>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-blue-600">业务事件</div>
                  <h2 className="mt-1 text-xl font-bold tracking-tight">{selectedMail.business}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-neutral-500">{selectedMail.aiSummary}</p>
                </div>
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-blue-50 text-blue-700">
                  {selectedMail.bucket === "security" ? "🛡" : "AI"}
                </div>
              </div>

              <div className="mt-4 rounded-2xl bg-neutral-50 p-4">
                <div className="text-xs font-semibold text-neutral-500">AI 建议动作</div>
                <p className="mt-1 text-sm font-semibold leading-relaxed text-neutral-950">{selectedMail.action}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (!completed.includes(selectedMail.id)) setCompleted((items) => [...items, selectedMail.id]);
                    }}
                    className="rounded-full bg-neutral-950 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-neutral-800"
                  >
                    {completed.includes(selectedMail.id) ? "已标记处理" : "标记已处理"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setArchived((items) => [...items, selectedMail.id])}
                    className="rounded-full bg-neutral-100 px-3 py-1.5 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-200"
                  >
                    归档
                  </button>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                {selectedMail.extracted.map((item) => (
                  <div key={item.label} className="rounded-2xl bg-neutral-50 p-3">
                    <div className="text-[11px] text-neutral-500">{item.label}</div>
                    <div className="mt-1 break-words text-sm font-semibold text-neutral-950">{item.value}</div>
                  </div>
                ))}
              </div>

              <div className="mt-4 rounded-2xl bg-blue-50 p-4 ring-1 ring-blue-100">
                <div className="text-xs font-bold text-blue-700">为什么这么分</div>
                <p className="mt-2 text-sm leading-relaxed text-blue-900">{selectedMail.aiReason}</p>
              </div>

              {selectedMail.timeline ? (
                <div className="mt-4 rounded-2xl bg-emerald-50 p-4 ring-1 ring-emerald-100">
                  <div className="text-xs font-bold text-emerald-800">合并后的时间线</div>
                  <div className="mt-4 space-y-3">
                    {selectedMail.timeline.map((event) => (
                      <div key={`${event.label}-${event.time}`} className="grid grid-cols-[28px_1fr] gap-3">
                        <div className="grid h-7 w-7 place-items-center rounded-full bg-white text-xs text-emerald-700 ring-1 ring-emerald-100">
                          {event.state === "next" ? "○" : "✓"}
                        </div>
                        <div>
                          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            <span className="text-sm font-bold text-emerald-950">{event.label}</span>
                            <span className="font-mono text-[11px] text-emerald-700">{event.time}</span>
                          </div>
                          <p className="mt-0.5 text-xs leading-relaxed text-emerald-800">{event.text}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-4 rounded-2xl border border-neutral-200 bg-white p-4">
                <div className="text-xs font-semibold text-neutral-500">原邮件片段</div>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{selectedMail.raw}</p>
              </div>
            </>
          ) : (
            <div className="grid min-h-[420px] place-items-center text-center">
              <div>
                <h2 className="text-lg font-bold text-neutral-950">右侧没有业务事件</h2>
                <p className="mt-2 max-w-xs text-sm leading-relaxed text-neutral-500">
                  当前筛选没有命中邮件，所以不会显示错位详情。
                </p>
              </div>
            </div>
          )}
        </aside>
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-neutral-50 p-3">
      <div className="text-[11px] text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-bold text-neutral-950">{value}</div>
    </div>
  );
}

function matchesBucket(mail: DemoMail, bucket: Bucket) {
  return mail.bucket === bucket || mail.relatedBuckets?.includes(bucket);
}
