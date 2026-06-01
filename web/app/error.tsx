"use client";

import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("mailhub route error", error);
  }, [error]);

  return (
    <main className="min-h-screen bg-neutral-50 flex items-center justify-center p-6">
      <div className="max-w-md w-full rounded-3xl bg-white shadow-sm ring-1 ring-black/5 p-6 text-center">
        <div className="text-[13px] font-semibold text-red-600 mb-2">前端刚刚崩了一下</div>
        <h1 className="text-[22px] font-semibold text-neutral-950">已拦截页面异常</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-neutral-500">
          通常是浏览器还拿着旧版本资源。点下面重试会重新拉取最新页面，不影响邮箱数据。
        </p>
        <div className="mt-5 flex gap-2 justify-center">
          <button onClick={reset} className="rounded-xl bg-[#007AFF] px-4 py-2 text-[14px] font-medium text-white">
            重试
          </button>
          <button onClick={() => window.location.reload()} className="rounded-xl bg-neutral-100 px-4 py-2 text-[14px] font-medium text-neutral-700">
            刷新页面
          </button>
        </div>
      </div>
    </main>
  );
}
