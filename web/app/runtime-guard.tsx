"use client";

import { useEffect } from "react";

const RELOAD_KEY = "mailhub.runtime-reload-at";
const CACHE_CLEAN_KEY = "mailhub.cache-cleaned-at";
const RELOAD_WINDOW_MS = 60_000;

function shouldReloadForRuntimeError(message: string) {
  return /ChunkLoadError|Loading chunk|dynamically imported module|module script|_next\/static|client-side exception/i.test(message);
}

async function clearBrowserCaches() {
  if ("serviceWorker" in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.map((reg) => reg.unregister().catch(() => false)));
  }
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key).catch(() => false)));
  }
}

function reloadOnce(message: string) {
  if (!shouldReloadForRuntimeError(message)) return;

  const last = Number(sessionStorage.getItem(RELOAD_KEY) || "0");
  if (Date.now() - last < RELOAD_WINDOW_MS) return;

  sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  clearBrowserCaches().finally(() => window.location.reload());
}

export default function ClientRuntimeGuard() {
  useEffect(() => {
    const cleanedAt = Number(localStorage.getItem(CACHE_CLEAN_KEY) || "0");
    if (Date.now() - cleanedAt > 24 * 60 * 60 * 1000) {
      localStorage.setItem(CACHE_CLEAN_KEY, String(Date.now()));
      clearBrowserCaches().catch(() => {});
    }

    const onError = (event: ErrorEvent) => {
      reloadOnce(`${event.message || ""} ${event.error?.message || ""} ${event.filename || ""}`);
    };
    const onUnhandled = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      reloadOnce(typeof reason === "string" ? reason : `${reason?.message || ""} ${reason?.stack || ""}`);
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandled);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandled);
    };
  }, []);

  return null;
}
